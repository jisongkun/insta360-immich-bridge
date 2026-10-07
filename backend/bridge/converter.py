import json
import os
import signal
import subprocess
import sys
import uuid
from pathlib import Path


class Converter:
    def manifest(self, job_id, group, profile, root):
        ext = "jpg" if group["kind"] == "photo" else "mp4"
        return {
            "sources": [f["path"] for f in group["files"]],
            "profile": profile,
            "capture_time": group["capture_time"],
            "timestamp": group["timestamp"],
            "output": str(root / f"{job_id}.{ext}"),
            "work_dir": str(root),
            "result": str(root / "result.json"),
            "debug": False,
        }

    def convert(self, job_id, group, profile, config, cancel_event, on_event):
        root = Path(config.data["work_dir"]) / "jobs" / job_id / str(uuid.uuid4())
        root.mkdir(parents=True, exist_ok=False)
        data = self.manifest(job_id, group, profile, root)
        data.update(
            sdk_executable=profile.get("sdk_executable", config.data["sdk_executable"]),
            model_root=profile.get("model_root", config.data["model_root"]),
        )
        if (
            profile.get("sdk_binary_sha256")
            and config.file_identity(data["sdk_executable"])
            != profile["sdk_binary_sha256"]
        ):
            raise ValueError(
                "SDK binary changed since task was queued; regenerate with current settings"
            )
        effective = config.changed(
            {"sdk_executable": data["sdk_executable"], "model_root": data["model_root"]}
        ).recipe()
        if (
            profile.get("models_sha256")
            and effective["models_sha256"] != profile["models_sha256"]
        ):
            raise ValueError("SDK model files changed since task was queued")
        request = root / "request.json"
        request.write_text(json.dumps(data))
        log = root / "controller.log"
        env = os.environ.copy()
        env["PATH"] = (
            str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        )
        # Keys are used solely by the parent bridge, never handed to the converter.
        env.pop(config.data["api_key_env"], None)
        env.pop(config.data["login_token_env"], None)
        env["AUTO_STITCHER_DB"] = str(root / "conversion.db")
        env["AUTO_STITCHER_DEBUG"] = "0"
        with log.open("wb") as output:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "convert_job.py"),
                    str(request),
                ],
                stdout=output,
                stderr=output,
                env=env,
                start_new_session=True,
            )
            on_event(
                "converting",
                {"work_dir": str(root), "output": data["output"], "pid": process.pid},
            )
            while process.poll() is None:
                oversize = any(
                    p.stat().st_size > config.data["log_max_bytes"]
                    for p in root.rglob("*.log")
                )
                if cancel_event.wait(0.5) or oversize:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    if oversize:
                        raise ValueError(
                            "SDK log size limit exceeded; originals retained"
                        )
                    raise InterruptedError("Conversion cancelled; originals retained")
        if process.returncode != 0 or not Path(data["result"]).exists():
            raise ValueError("Existing converter failed; inspect task logs")
        result = json.loads(Path(data["result"]).read_text())
        if result["status"] != "processed":
            raise ValueError("Existing converter did not complete")
        self.check_logs(root)
        return Path(data["output"])

    @staticmethod
    def check_logs(root):
        # The SDK example can report an error and still return 0.
        import re

        for path in root.rglob("*.log"):
            with path.open(errors="replace") as handle:
                for line in handle:
                    if re.search(
                        r"(?i)(^error:|\[error\]|\[fatal\]|model.*(missing|not found)|feature.*(unsupported|failed))",
                        line,
                    ):
                        raise ValueError(
                            "SDK reported an error or missing feature; inspect task logs"
                        )
