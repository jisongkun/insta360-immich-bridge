import hashlib
import threading
from pathlib import Path
from bridge.config import BridgeConfig
from bridge.store import Store
from bridge.pipeline import Pipeline


class Client:
    base = "http://immich/api"

    def __init__(self):
        self.media = {}
        self.actions = []
        self.fail = ""
        self.uploads = 0

    def identify(self):
        return {"user_id": "user", "server": self.base}

    def asset(self, id):
        return {"id": id, "isTrashed": id in getattr(self, "trashed", set())}

    def find_checksum(self, sha):
        return next(
            (
                {"id": k, "status": "duplicate"}
                for k, v in self.media.items()
                if hashlib.sha1(v).hexdigest() == sha
            ),
            None,
        )

    def upload(self, path, date, sha):
        self.uploads += 1
        id = f"asset-{self.uploads}"
        self.media[id] = path.read_bytes()
        if self.fail == "timeout":
            self.fail = ""
            raise RuntimeError("network")
        self.actions.append("upload")
        return {"id": id, "status": "created"}

    def download(self, id, destination, max_bytes=None):
        if self.fail == "verify":
            raise RuntimeError("network")
        data = self.media[id]
        self.actions.append("verify:" + id)
        if max_bytes is not None and len(data) != max_bytes:
            raise ValueError("size mismatch")
        return hashlib.sha256(data).hexdigest()

    def copy(self, a, b, opts):
        self.actions.append("copy")
        assert opts["sidecar"] is False

    def trash(self, id):
        self.actions.append("trash")
        self.trashed = getattr(self, "trashed", set()) | {id}
        if self.fail == "trash":
            self.fail = ""
            raise RuntimeError("network")


class Converter:
    def __init__(self):
        self.calls = 0
        self.data = b"output"

    def convert(self, id, group, profile, config, cancel, on_event):
        self.calls += 1
        root = Path(config.data["work_dir"]) / "jobs" / id / "attempt"
        root.mkdir(parents=True, exist_ok=True)
        output = root / "video.mp4"
        output.write_bytes(self.data)
        on_event("converting", {"work_dir": str(root), "output": str(output)})
        return output


def setup(tmp_path):
    config = BridgeConfig(
        {"state_dir": str(tmp_path / "state"), "work_dir": str(tmp_path / "work")}
    ).validate()
    store = Store(tmp_path / "state/db")
    client = Client()
    converter = Converter()
    group = {
        "id": "source",
        "kind": "video",
        "timestamp": "20261007_120000",
        "capture_time": "2026-10-07T12:00:00+08:00",
        "files": [],
    }
    target = client.base + "|user"
    store.set("target", target)
    id = store.enqueue(group, config.recipe(), target)
    pipeline = Pipeline(store, client, converter, config, validator=lambda *a: None)
    return store, client, converter, config, group, id, pipeline


def test_receipt_cleanup_restart_dedup(tmp_path):
    store, client, converter, config, group, id, p = setup(tmp_path)
    p.process(id, threading.Event())
    job = store.job(id)
    assert job["stage"] == "done" and job["verified"] and job["owned"]
    assert not Path(job["output"]).exists()
    store = Store(store.path)
    p = Pipeline(store, client, converter, config, validator=lambda *a: None)
    p.process(id, threading.Event())
    assert converter.calls == 1 and client.uploads == 1
    assert store.enqueue(group, config.recipe(), job["target"]) == id


def test_upload_timeout_and_verification_failure_keep_output(tmp_path):
    store, client, c, config, g, id, p = setup(tmp_path)
    client.fail = "timeout"
    p.process(id, threading.Event())
    assert store.job(id)["stage"] == "failed" and Path(store.job(id)["output"]).exists()
    client.fail = "verify"
    p.process(id, threading.Event())
    assert c.calls == 1 and client.uploads == 1
    client.fail = ""
    p.process(id, threading.Event())
    assert store.job(id)["stage"] == "done"
    assert not store.job(id)["owned"]  # response lost: do not invent ownership


def test_replace_only_after_verification_and_copy_trash_readback(tmp_path):
    store, client, c, config, g, id, p = setup(tmp_path)
    p.process(id, threading.Event())
    old = store.job(id)["asset_id"]
    c.data = b"new output"
    new = store.enqueue(
        g,
        {**config.recipe(), "bitrate": "200000000"},
        store.job(id)["target"],
        force=True,
    )
    store.update(new, replace=True)
    client.actions = []
    client.fail = "trash"
    p.process(new, threading.Event())
    assert client.actions[:3] == ["upload", "verify:asset-2", "verify:" + old]
    assert client.actions.index("copy") < client.actions.index("trash")
    p.process(new, threading.Event())
    assert store.job(new)["stage"] == "done" and c.calls == 2
    assert store.job(id)["replaced_by"] == new


def test_unowned_duplicate_does_not_mutate_prior_or_source(tmp_path):
    store, client, c, config, g, id, p = setup(tmp_path)
    p.process(id, threading.Event())
    client.media["unrelated"] = b"other"
    c.data = b"other"
    new = store.enqueue(g, config.recipe(), store.job(id)["target"], force=True)
    store.update(new, replace=True)
    client.actions = []
    p.process(new, threading.Event())
    assert store.job(new)["stage"] == "failed"
    assert "copy" not in client.actions and "trash" not in client.actions
    assert Path(store.job(new)["output"]).exists()


def test_same_asset_no_trash_and_changed_old_blocks_replace(tmp_path):
    store, client, c, config, g, id, p = setup(tmp_path)
    p.process(id, threading.Event())
    new = store.enqueue(g, config.recipe(), store.job(id)["target"], force=True)
    store.update(new, replace=True)
    p.process(new, threading.Event())
    assert store.job(new)["stage"] == "done" and "trash" not in client.actions
    c.data = b"new"
    client.media[store.job(new)["asset_id"]] = b"edited"
    newer = store.enqueue(g, config.recipe(), store.job(id)["target"], force=True)
    store.update(newer, replace=True)
    p.process(newer, threading.Event())
    assert store.job(newer)["stage"] == "failed" and "copy" not in client.actions


def test_cleanup_refuses_source_and_wrong_target(tmp_path):
    store, client, c, config, g, id, p = setup(tmp_path)
    store.update(
        id, phase="cleanup", verified=True, output=str(tmp_path / "original.insv")
    )
    Path(tmp_path / "original.insv").write_bytes(b"original")
    p.process(id, threading.Event())
    assert (
        store.job(id)["stage"] == "failed" and Path(tmp_path / "original.insv").exists()
    )
    other = store.enqueue(g, config.recipe(), "http://other/api|user")
    p.process(other, threading.Event())
    assert store.job(other)["stage"] == "failed" and c.calls == 0


def test_multiple_regenerations_replace_current_generation_in_order(tmp_path):
    store, client, c, config, g, id, p = setup(tmp_path)
    p.process(id, threading.Event())
    a = store.enqueue(g, config.recipe(), store.job(id)["target"], force=True)
    store.update(a, replace=True)
    b = store.enqueue(g, config.recipe(), store.job(id)["target"], force=True)
    store.update(b, replace=True)
    c.data = b"second"
    p.process(a, threading.Event())
    second = store.job(a)["asset_id"]
    c.data = b"third"
    p.process(b, threading.Event())
    assert second in client.trashed
    assert store.job(b)["previous"]["asset_id"] == second


def test_api_transient_failure_has_bounded_retry_state(tmp_path):
    from bridge.immich import ImmichError

    store, client, c, config, g, id, p = setup(tmp_path)
    client.download = lambda *a, **kw: (_ for _ in ()).throw(ImmichError(503))
    p.process(id, threading.Event())
    job = store.job(id)
    assert (
        job["retryable"] and job["retry_at"] > job["updated"] and job["attempts"] == 1
    )
