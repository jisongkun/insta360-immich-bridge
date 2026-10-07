import threading
import time
from pathlib import Path
from bridge.immich import ImmichError
from test_pipeline import setup as pipeline_setup
from test_service import setup as service_setup


def wait(service):
    for _ in range(200):
        if not service.active_tasks:
            return
        time.sleep(0.01)
    raise AssertionError("Task did not finish")


def test_cancel_after_verification_preserves_replacement(tmp_path):
    store, client, converter, config, group, original, pipeline = pipeline_setup(
        tmp_path
    )
    pipeline.process(original, threading.Event())
    new = store.enqueue(
        group, config.recipe(), store.job(original)["target"], force=True
    )
    store.update(new, replace=True)
    converter.data = b"new export"
    cancel = threading.Event()
    download = client.download

    def interrupted(*args, **kwargs):
        result = download(*args, **kwargs)
        cancel.set()
        return result

    client.download = interrupted
    client.actions = []
    pipeline.process(new, cancel)
    assert store.job(new)["stage"] == "cancelled"
    assert store.job(new)["verified"]
    assert "copy" not in client.actions and "trash" not in client.actions
    assert Path(store.job(new)["output"]).exists()
    client.download = download
    store.update(new, stage="pending")
    pipeline.process(new, threading.Event())
    assert store.job(new)["stage"] == "done"


def test_failed_delivery_blocks_later_generation_until_resumed(tmp_path):
    store, client, converter, config, group, original, pipeline = pipeline_setup(
        tmp_path
    )
    pipeline.process(original, threading.Event())
    a = store.enqueue(group, config.recipe(), store.job(original)["target"], force=True)
    store.update(a, replace=True)
    converter.data = b"second"
    copy = client.copy
    client.copy = lambda *a: (_ for _ in ()).throw(ImmichError(403))
    pipeline.process(a, threading.Event())
    assert store.job(a)["phase"] == "replacing"
    b = store.enqueue(group, config.recipe(), store.job(original)["target"], force=True)
    store.update(b, replace=True)
    converter.data = b"third"
    pipeline.process(b, threading.Event())
    assert store.job(b)["stage"] == "pending" and converter.calls == 2
    client.copy = copy
    pipeline.process(a, threading.Event())
    pipeline.process(b, threading.Event())
    assert store.job(a)["replaced_by"] == b
    assert store.job(a)["asset_id"] in client.trashed


def test_restart_dispatch_only_requested_ids(tmp_path, monkeypatch):
    service = service_setup(tmp_path, monkeypatch)
    first = service.store.enqueue({"id": "one"}, {}, "target")
    second = service.store.enqueue({"id": "two"}, {}, "target")
    service.store.update(first, run_requested=True)
    calls = []
    service.run_jobs = lambda ids=None, **kwargs: calls.append(ids)
    service.start()
    wait(service)
    service.close()
    assert calls == [[first]] and second not in calls[0]


def test_folder_source_can_disable_api_discovery(tmp_path, monkeypatch):
    service = service_setup(tmp_path, monkeypatch)
    service.configure(
        {
            "immich_url": "http://immich",
            "api_source_enabled": False,
            "folders": [str(tmp_path / "source")],
        }
    )
    called = []
    monkeypatch.setattr(
        "bridge.service.discover_immich",
        lambda *a: (_ for _ in ()).throw(AssertionError("API discovery used")),
    )
    monkeypatch.setattr(
        "bridge.service.discover_folders", lambda *a: called.append("folder") or []
    )
    service.scan()
    assert called == ["folder"]
    service.close()


def test_automatic_excludes_photos_and_replacement_permission_does_not_pause(
    tmp_path, monkeypatch
):
    service = service_setup(tmp_path, monkeypatch)
    service.configure({"immich_url": "http://immich", "automatic": True})
    service.connect = lambda: (
        type("Client", (), {"base": "http://immich/api"})(),
        "target",
    )
    video = service.store.enqueue({"id": "video", "kind": "video"}, {}, "target")
    photo = service.store.enqueue({"id": "photo", "kind": "photo"}, {}, "target")
    replacement = service.store.enqueue({"id": "old", "kind": "video"}, {}, "target")

    def process(self, id, cancel):
        if id == replacement:
            service.store.update(id, stage="failed", phase="replacing", http_status=403)
        else:
            service.store.update(id, stage="done")

    monkeypatch.setattr("bridge.service.Pipeline.process", process)
    service.scan = lambda *a, **kw: None
    service.tick(time.time())
    wait(service)
    assert service.store.job(video)["stage"] == "done"
    assert service.store.job(photo)["stage"] == "pending"
    assert not service.store.get("api_paused", False)
    service.configure({"automatic_photos": True})
    service.run_jobs(automatic=True)
    assert service.store.job(photo)["stage"] == "done"
    service.close()


def test_capture_metadata_precedes_filename_and_survives_regeneration(
    tmp_path, monkeypatch
):
    from bridge.discovery import group_files

    service = service_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "bridge.discovery.source_capture_time",
        lambda *a: ("2026-10-07T03:00:00+02:00", "metadata"),
    )
    monkeypatch.setattr("bridge.discovery.stream_count", lambda *a: 2)
    file = dict(
        path="raw.insv",
        scope="one",
        prefix="VID",
        timestamp="20261007_120000",
        segment="001",
        role="00",
        kind="video",
        sha256="abc",
    )
    group = group_files([file], service.config, service.store)[0]
    assert group["capture_time"] == "2026-10-07T03:00:00+02:00"
    id = service.store.enqueue(group, service.config.recipe(), "target")
    service.store.update(id, stage="done", owned=True, verified=True, asset_id="old")
    new = service.regenerate([id])[0]
    assert service.store.job(new)["group"]["capture_time"] == group["capture_time"]
    service.close()


def test_unknown_auto_projection_is_blocked_and_disk_preflight(tmp_path, monkeypatch):
    from bridge.converter import Converter
    from bridge.config import BridgeConfig
    import pytest

    config = BridgeConfig(
        {"state_dir": str(tmp_path / "state"), "work_dir": str(tmp_path / "work")}
    )
    group = {
        "files": [{"path": "raw.insv", "stat": [0, 0, 100, 0, 0]}],
        "kind": "video",
    }
    monkeypatch.setattr(
        "bridge.converter.probe",
        lambda *a: {
            "width": 1920,
            "height": 1080,
            "duration": 1,
            "raw": {"streams": []},
        },
    )
    with pytest.raises(ValueError, match="fixed"):
        Converter.effective_profile(group, {**config.recipe(), "auto_resolution": True})
    monkeypatch.setattr(
        "bridge.converter.shutil.disk_usage",
        lambda *a: type("Usage", (), {"free": 1})(),
    )
    with pytest.raises(ValueError, match="space"):
        Converter.check_space(group, config.recipe(), config)


def test_validation_failure_can_reconvert_and_new_recipe_is_not_blocked(tmp_path):
    store, client, converter, config, group, id, pipeline = pipeline_setup(tmp_path)
    pipeline.validator = lambda *a: (_ for _ in ()).throw(ValueError("Invalid media"))
    pipeline.process(id, threading.Event())
    assert store.job(id)["stage"] == "failed"
    pipeline.validator = lambda *a: None
    pipeline.process(id, threading.Event())
    assert store.job(id)["stage"] == "done" and converter.calls == 2
    other = store.enqueue(
        {
            "id": "another",
            "kind": "video",
            "files": [],
            "capture_time": group["capture_time"],
        },
        config.recipe(),
        store.job(id)["target"],
    )
    pipeline.validator = lambda *a: (_ for _ in ()).throw(ValueError("Invalid media"))
    pipeline.process(other, threading.Event())
    newer = store.enqueue(
        store.job(other)["group"],
        {**config.recipe(), "bitrate": "200000000"},
        store.job(id)["target"],
    )
    pipeline.validator = lambda *a: None
    pipeline.process(newer, threading.Event())
    assert store.job(newer)["stage"] == "done"


def test_missing_or_edited_new_export_blocks_old_trash_on_resume(tmp_path):
    store, client, converter, config, group, original, pipeline = pipeline_setup(
        tmp_path
    )
    pipeline.process(original, threading.Event())
    new = store.enqueue(
        group, config.recipe(), store.job(original)["target"], force=True
    )
    store.update(new, replace=True)
    converter.data = b"new export"
    trash = client.trash
    client.trash = lambda *a: (_ for _ in ()).throw(ImmichError(503))
    pipeline.process(new, threading.Event())
    assert store.job(new)["copied"]
    current = store.job(new)["asset_id"]
    old = store.job(original)["asset_id"]
    client.trash = trash
    client.trashed = {current}
    pipeline.process(new, threading.Event())
    assert store.job(new)["stage"] == "failed" and old not in client.trashed
    assert Path(store.job(new)["output"]).exists()
    client.trashed = set()
    saved = client.media[current]
    client.media[current] = b"changed!"
    pipeline.process(new, threading.Event())
    assert store.job(new)["stage"] == "failed" and old not in client.trashed
    client.media[current] = saved
    pipeline.process(new, threading.Event())
    assert store.job(new)["stage"] == "done" and old in client.trashed
