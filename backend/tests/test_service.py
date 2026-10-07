import os
import threading
import time
import pytest
from bridge.config import BridgeConfig
from bridge.service import Service
from bridge.app import create_app


def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIDGE_LOGIN_TOKEN", "test-login")
    config = BridgeConfig(
        {"state_dir": str(tmp_path / "state"), "work_dir": str(tmp_path / "work")},
        tmp_path / "config.json",
    ).validate()
    return Service(config)


def test_api_auth_redaction_and_no_restart_loop(tmp_path, monkeypatch):
    service = setup(tmp_path, monkeypatch)
    app = create_app(service)
    client = app.test_client()
    assert client.get("/status").status_code == 401
    assert client.post("/login", json={"token": "wrong"}).status_code == 401
    assert client.post("/login", json={"token": "test-login"}).status_code == 200
    auth = {"Authorization": "Bearer test-login"}
    assert client.get("/status", headers=auth).status_code == 200
    assert (
        client.post(
            "/settings/bridge", headers=auth, json={"api_key": "secret"}
        ).status_code
        == 400
    )
    assert (
        client.post("/settings/bridge", headers=auth, json={"interval": 0}).status_code
        == 400
    )
    assert (
        client.post(
            "/settings/bridge", headers=auth, json={"automatic": False, "interval": 120}
        ).status_code
        == 200
    )
    assert "secret" not in client.get("/settings/bridge", headers=auth).text
    assert (
        client.post("/tasks", headers=auth, json={"action": "whatever"}).status_code
        == 400
    )
    assert client.get("/jobs/absent/logs", headers=auth).status_code == 404
    service.close()


def test_single_owner_and_scheduler_manual_coalescing(tmp_path, monkeypatch):
    service = setup(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError):
        Service(service.config)
    called = []
    release = threading.Event()

    def scan(full=False, folders=True, api=True):
        called.append(full)
        release.wait(2)

    service.scan = scan
    first = service.submit("scan")
    second = service.submit("scan")
    assert first == second
    release.set()
    for _ in range(40):
        if not service.active_tasks:
            break
        time.sleep(0.01)
    assert called == [False]
    assert service.config.data["automatic"] is False
    service.close()


def test_cancel_and_regenerate_require_managed_receipt(tmp_path, monkeypatch):
    s = setup(tmp_path, monkeypatch)
    group = {
        "id": "source",
        "files": [],
        "kind": "video",
        "timestamp": "20261007_120000",
        "capture_time": "2026-10-07T12:00:00+08:00",
    }
    id = s.store.enqueue(group, s.config.recipe(), "target")
    s.store.update(id, stage="done", verified=True, owned=False)
    with pytest.raises(ValueError):
        s.regenerate([id])
    s.store.update(id, owned=True, asset_id="old")
    new = s.regenerate([id])[0]
    assert s.store.job(new)["replace"]
    # Config updates never mutate the immutable recipe already queued.
    old_profile = s.store.job(new)["profile"]
    s.configure({"profile": {**s.config.data["profile"], "bitrate": "200000000"}})
    assert s.store.job(new)["profile"] == old_profile
    s.close()


def test_interval_due_is_based_on_attempt_and_auth_all_read_routes(
    tmp_path, monkeypatch
):
    s = setup(tmp_path, monkeypatch)
    s.configure(
        {
            "automatic": True,
            "immich_url": "http://immich",
            "folders": [str(tmp_path / "source")],
        }
    )
    s.store.set("last_api_attempt", 100)
    s.store.set("last_folder_attempt", 100)
    s.store.set("last_full_attempt", 100)
    s.tick(110)
    assert not s.active_tasks
    app = create_app(s)
    client = app.test_client()
    for path in (
        "/settings/bridge",
        "/events",
        "/jobs/absent/details",
        "/jobs/absent/events",
        "/jobs/absent/logs",
        "/thumbnails/absent.jpg",
    ):
        assert client.get(path).status_code == 401
    s.close()


def test_log_retention_never_removes_receipts_or_sources(tmp_path, monkeypatch):
    from pathlib import Path

    s = setup(tmp_path, monkeypatch)
    group = {
        "id": "source",
        "files": [],
        "kind": "video",
        "timestamp": "20261007_120000",
        "capture_time": "2026-10-07T12:00:00+08:00",
    }
    id = s.store.enqueue(group, s.config.recipe(), "target")
    s.store.update(id, stage="done", verified=True, asset_id="receipt")
    root = Path(s.config.data["work_dir"]) / "jobs" / id / "attempt"
    root.mkdir(parents=True)
    log = root / "sdk.log"
    log.write_text("old")
    os.utime(log, (1, 1))
    receipt = root / "result.json"
    receipt.write_text("{}")
    os.utime(receipt, (1, 1))
    s.maintain_logs(4000000)
    assert not log.exists() and receipt.exists() and s.store.job(id)["verified"]
    s.close()
