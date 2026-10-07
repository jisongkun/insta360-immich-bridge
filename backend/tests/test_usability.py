"""Regressions for user-visible setup, Save and task control failures."""

import threading
from pathlib import Path
import pytest
from bridge.app import create_app
from bridge.config import BridgeConfig
from test_service import setup


@pytest.fixture
def service(tmp_path, monkeypatch):
    instance = setup(tmp_path, monkeypatch)
    yield instance
    instance.close()


def api(service):
    client = create_app(service).test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = "Bearer test-login"
    return client


def group(name="source"):
    return dict(
        id=name,
        files=[],
        kind="video",
        timestamp="20261007_120000",
        capture_time="2026-10-07T12:00:00+08:00",
    )


def test_entered_key_is_persisted_privately_and_never_returned(service):
    client = api(service)
    response = client.post(
        "/settings/bridge",
        json={
            "immich_url": "http://immich",
            "immich_api_key": "entered-private-key",
        },
    )
    assert response.status_code == 200
    reloaded = BridgeConfig.load(service.config.path)
    assert reloaded.key() == "entered-private-key"
    assert Path(reloaded.data["api_key_file"]).stat().st_mode & 0o777 == 0o600
    assert "entered-private-key" not in service.config.path.read_text()
    for route in ("/settings/bridge", "/status", "/events"):
        assert "entered-private-key" not in client.get(route).text
    assert "entered-private-key" not in response.text


def test_blank_key_preserves_installed_read_only_secret(service, tmp_path):
    installed = tmp_path / "installed-key"
    installed.write_text("installed-secret")
    service.configure({"api_key_file": str(installed)})
    response = api(service).post(
        "/settings/bridge",
        json={
            "immich_api_key": "",
            "interval": 120,
        },
    )
    assert response.status_code == 200
    assert service.config.key() == "installed-secret"
    assert service.config.data["api_key_file"] == str(installed)
    assert installed.read_text() == "installed-secret"


def test_invalid_settings_do_not_install_a_new_key_or_change_ratio(service, tmp_path):
    service.store.set("expected_ratio", 0.75)
    before = service.config.public()
    response = api(service).post(
        "/settings/bridge",
        json={
            "interval": 120,
            "expected_size_ratio": 2,
            "immich_api_key": "must-not-be-written",
            "profile": {"output_size": "bad"},
        },
    )
    assert response.status_code == 400
    assert service.config.public() == before
    assert service.store.get("expected_ratio") == 0.75
    assert not list(tmp_path.rglob("*.key"))


def test_single_settings_save_updates_profile_parallelism_and_ratio(service):
    response = api(service).post(
        "/settings/bridge",
        json={
            "stitch_parallelism": 2,
            "expected_size_ratio": 0.5,
            "profile": {"output_size": "3840x1920", "bitrate": "200000000"},
        },
    )
    assert response.status_code == 200
    assert service.config.data["stitch_parallelism"] == 2
    assert service.config.data["profile"]["output_size"] == "3840x1920"
    assert service.store.get("expected_ratio") == 0.5


def test_compute_ratio_is_a_draft_until_save(service):
    source = group()
    source["files"] = [{"stat": [1, 2, 100, 4, 5]}]
    job = service.store.enqueue(source, {}, "target")
    service.store.update(job, verified=True, output_bytes=200)
    service.store.set("expected_ratio", 0.75)
    response = api(service).post("/settings/ratio/compute", json={})
    assert response.status_code == 200
    assert response.json["expected_size_ratio"] == 2
    assert service.store.get("expected_ratio") == 0.75


def test_connection_change_invalidates_verified_status_and_target(service):
    service.configure({"immich_url": "http://old"})
    service.connection = {"ok": True, "server": "http://old/api"}
    service.store.set("connection", service.connection)
    service.store.set("target", "http://old/api|old-owner")
    service.configure({"immich_url": "http://new"})
    assert not service.status()["connection"].get("ok")
    assert not service.store.get("target")
    assert not service.store.get("connection").get("ok")


def test_folder_discovery_verifies_current_target_before_queueing(service, monkeypatch):
    service.configure(
        {
            "immich_url": "http://new",
            "api_source_enabled": False,
            "folders": ["/source"],
        }
    )

    class Client:
        base = "http://new/api"

        def identify(self):
            return {"user_id": "new-owner", "server": self.base, "version": "v3.2.4"}

    monkeypatch.setattr(service, "client", lambda: Client())
    monkeypatch.setattr("bridge.service.discover_folders", lambda *a, **k: [group()])
    service.store.set("target", "http://old/api|old-owner")
    service.scan(api=False)
    assert service.store.jobs()[0]["target"] == "http://new/api|new-owner"


@pytest.mark.parametrize("action", ["stitch_selected", "regenerate_selected"])
def test_busy_run_rejects_selected_work_instead_of_silently_dropping_it(
    service, monkeypatch, action
):
    job = service.store.enqueue(group(), {}, "target")
    service.store.update(job, stage="done", verified=True, owned=True, asset_id="old")
    started, release = threading.Event(), threading.Event()

    def running(*args, **kwargs):
        started.set()
        release.wait(2)

    monkeypatch.setattr(service, "run_jobs", running)
    task = service.submit("stitch")
    assert started.wait(2)
    worker = service.active_tasks[task]["thread"]
    try:
        with pytest.raises(ValueError, match="running"):
            service.submit(action, [job])
        assert len(service.store.jobs()) == 1
    finally:
        release.set()
        worker.join(2)


def test_missing_secret_file_does_not_break_status_or_event_logging(service, tmp_path):
    service.configure({"api_key_file": str(tmp_path / "missing-key")})
    service.event("connection", "Please configure an API key")
    assert api(service).get("/status").status_code == 200
    assert service.config.key() == ""


def test_cancelled_thumbnail_task_does_not_start_later_jobs(service, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = []
    for name in ("one", "two", "three"):
        source = group(name)
        source["files"] = [{"path": name}]
        service.store.enqueue(source, {}, "target")
    service.configure({"thumbnail_parallelism": 1})

    class Legacy:
        def video_duration_seconds(self, path):
            return 1

        def extract_thumbnail(self, source, output, at):
            calls.append(source)
            started.set()
            release.wait(2)
            return False

    monkeypatch.setattr("bridge.service.load", lambda: Legacy())
    task = service.submit("generate_thumbnails")
    try:
        assert started.wait(2)
        worker = service.active_tasks[task]["thread"]
        service.cancel(task)
        release.set()
        worker.join(2)
        assert not worker.is_alive()
        assert len(calls) == 1
    finally:
        release.set()


def test_discovery_stop_preserves_connection_and_does_not_queue(service, monkeypatch):
    from concurrent.futures import CancelledError

    service.configure({"immich_url": "http://immich"})
    started = threading.Event()

    def discovery(client, config, store, full=False, cancel=None):
        started.set()
        assert cancel.wait(2)
        raise CancelledError()

    monkeypatch.setattr(service, "connect", lambda: (object(), "target"))
    monkeypatch.setattr("bridge.service.discover_immich", discovery)
    service.connection = {"ok": True}
    task = service.submit("scan")
    try:
        assert started.wait(2)
        worker = service.active_tasks[task]["thread"]
        service.cancel(task)
        worker.join(2)
        assert not worker.is_alive()
        assert service.connection["ok"]
        assert not service.store.jobs()
    finally:
        with service.guard:
            if task in service.cancels:
                service.cancels[task].set()


def test_cancel_between_api_pages_preserves_previous_index_and_watermark(service):
    from concurrent.futures import CancelledError
    from bridge.discovery import discover_immich

    cancel = threading.Event()
    service.store.set("target", "target")
    service.store.set("api-index:target", {"old": {"id": "old"}})
    service.store.set("watermark:target", 100)

    class Client:
        base = "http://immich/api"
        server_time = 200
        calls = 0

        def search(self, filter, cursor):
            self.calls += 1
            if self.calls == 2:
                cancel.set()
            return {"items": [{"id": "new"}], "nextCursor": "next"}

    client = Client()
    with pytest.raises(CancelledError):
        discover_immich(client, service.config, service.store, cancel=cancel)
    assert client.calls == 2
    assert service.store.get("watermark:target") == 100
    assert service.store.get("api-index:target") == {"old": {"id": "old"}}


def test_cancelled_source_download_removes_partial_file(service, tmp_path):
    from concurrent.futures import CancelledError
    from bridge.discovery import discover_immich

    service.configure({"download_sources": True})
    cancel = threading.Event()

    class Client:
        base = "http://immich/api"
        server_time = 200

        def search(self, filter, cursor):
            return {
                "items": [
                    {
                        "id": "source",
                        "originalFileName": "VID_20261007_120000_00_001.insv",
                    }
                ],
                "nextCursor": None,
            }

        def download(self, id, handle, cancel=None):
            handle.write(b"partial")
            cancel.set()
            raise CancelledError()

    with pytest.raises(CancelledError):
        discover_immich(Client(), service.config, service.store, cancel=cancel)
    assert not list((tmp_path / "work").rglob("*.partial"))
    assert not list((tmp_path / "work").rglob("*.insv"))


def test_settings_write_failure_preserves_old_key_and_ratio(
    service, tmp_path, monkeypatch
):
    installed = tmp_path / "installed-key"
    installed.write_text("original-private-key")
    service.configure({"api_key_file": str(installed)})
    before = service.config.public()
    saved = service.config.path.read_text()

    def failure(config):
        raise OSError("Configuration volume unavailable")

    monkeypatch.setattr(BridgeConfig, "save", failure)
    with pytest.raises(OSError):
        service.configure(
            {"immich_api_key": "uncommitted-key", "expected_size_ratio": 2}
        )
    assert service.config.public() == before
    assert service.config.path.read_text() == saved
    assert service.config.key() == "original-private-key"
    assert service.store.get("expected_ratio", 1) == 1
    assert not list(tmp_path.rglob("*.key"))
