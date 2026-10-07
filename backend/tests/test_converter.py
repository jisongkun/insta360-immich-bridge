from pathlib import Path
import pytest
from bridge.legacy import load


def controller(tmp_path):
    legacy = load()
    legacy.configure_paths(str(tmp_path), str(tmp_path / "raw"), str(tmp_path / "out"))
    return legacy.AutoStitcher(debug=False)


def test_new_sdk_command_keeps_existing_features(tmp_path):
    c = controller(tmp_path)
    c.sdk_executable = "/opt/MediaSDK-3.1.5-linux/bin/MediaSDKTest"
    c.model_root = str(tmp_path / "models")
    Path(c.model_root).mkdir()
    command = c.build_sdk_command(["one.insv", "two.insv"], "out.mp4", "5760x2880")
    assert command[0] == c.sdk_executable
    assert "-disable_cuda" not in command
    assert "-enable_flowstate" in command and "-enable_h265_encoder" in command
    assert command[command.index("-model_root_dir") + 1].endswith("/")
    c.disable_cuda = True
    assert "-disable_cuda" in c.build_sdk_command(["one.insv"], "out.mp4", "5760x2880")
    c.stitch_type = "aistitch"
    c.model_root = str(tmp_path / "absent")
    with pytest.raises(ValueError):
        c.build_sdk_command(["one.insv"], "out.mp4", "5760x2880")


def test_gateway_request_uses_unique_workspace(tmp_path):
    from bridge.converter import Converter

    converter = Converter()
    group = {
        "id": "source",
        "files": [{"path": "/readonly/source.insv"}],
        "timestamp": "20261007_120000",
        "kind": "video",
        "capture_time": "2026-10-07T12:00:00+08:00",
    }
    manifest = converter.manifest("job", group, {"output_size": "5760x2880"}, tmp_path)
    assert manifest["sources"] == ["/readonly/source.insv"]
    assert Path(manifest["output"]).parent == tmp_path
    assert manifest["debug"] is False


def test_sdk_zero_exit_log_is_not_success(tmp_path):
    from bridge.converter import Converter

    root = tmp_path / "attempt"
    root.mkdir()
    (root / "sdk.log").write_text("[ERROR] unsupported feature\n")
    with pytest.raises(ValueError, match="SDK"):
        Converter.check_logs(root)


def test_gateway_runs_existing_worker_and_rejects_sdk_error(tmp_path):
    import json, subprocess, threading
    from bridge.config import BridgeConfig
    from bridge.converter import Converter
    from bridge.discovery import snapshot, hashes
    from bridge.validation import validate

    source = tmp_path / "VID_20261007_120000_00_001.insv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=128x64:rate=10",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-f",
            "mp4",
            str(source),
        ],
        check=True,
    )
    sdk = tmp_path / "fake-sdk"
    sdk.write_text(
        '#!/usr/bin/env python3\nimport sys,shutil\na=sys.argv\nshutil.copyfile(a[a.index("-inputs")+1],a[a.index("-output")+1])\n'
    )
    sdk.chmod(0o755)
    config = BridgeConfig(
        {
            "state_dir": str(tmp_path / "state"),
            "work_dir": str(tmp_path / "work"),
            "sdk_executable": str(sdk),
            "model_root": str(tmp_path / "models"),
            "profile": {"output_size": "128x64"},
        }
    ).validate()
    group = {
        "id": "fixture",
        "kind": "video",
        "timestamp": "20261007_120000",
        "capture_time": "2026-10-07T12:00:00+08:00",
        "files": [
            {"path": str(source), "stat": snapshot(source), "sha256": hashes(source)[0]}
        ],
    }
    output = Converter().convert(
        "job", group, config.recipe(), config, threading.Event(), lambda *_: None
    )
    assert output.exists() and validate(output, group, config.recipe())["duration"] == 1
    manifest = json.loads((output.parent / "request.json").read_text())
    assert manifest["capture_time"] == group["capture_time"]
    sdk.write_text(sdk.read_text() + 'print("error: encoder failure")\n')
    with pytest.raises(ValueError, match="SDK"):
        Converter().convert(
            "second", group, config.recipe(), config, threading.Event(), lambda *_: None
        )


def test_cancellation_stops_private_process_group(tmp_path):
    import threading
    from bridge.config import BridgeConfig
    from bridge.converter import Converter

    config = BridgeConfig(
        {"state_dir": str(tmp_path / "state"), "work_dir": str(tmp_path / "work")}
    )
    event = threading.Event()
    group = {
        "kind": "video",
        "files": [],
        "timestamp": "20261007_120000",
        "capture_time": "2026-10-07T12:00:00+08:00",
    }
    with pytest.raises(InterruptedError):
        Converter().convert(
            "cancel", group, config.recipe(), config, event, lambda *_: event.set()
        )
