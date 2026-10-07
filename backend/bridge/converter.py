import json
import os
import signal
import subprocess
import sys
import uuid
import shutil
from .validation import probe
from pathlib import Path


class Converter:
    @staticmethod
    def effective_profile(group, profile):
        if not profile.get("auto_resolution"):
            return profile
        source = probe(group["files"][0]["path"])
        spherical = any(
            d.get("side_data_type") == "Spherical Mapping"
            and d.get("projection") == "equirectangular"
            for stream in source["raw"]["streams"]
            for d in stream.get("side_data_list", [])
        )
        if (
            group["kind"] != "video"
            or not spherical
            or source["width"] != 2 * source["height"]
        ):
            raise ValueError(
                "Unknown source projection: select fixed output dimensions before stitching"
            )
        if source["width"] % 2 or source["height"] % 2:
            raise ValueError(
                "Invalid source dimensions: select fixed output dimensions"
            )
        return {
            **profile,
            "auto_resolution": False,
            "output_size": f"{source['width']}x{source['height']}",
        }

    @staticmethod
    def check_space(group, profile, config):
        root = Path(config.data["work_dir"])
        root.mkdir(parents=True, exist_ok=True)
        source_bytes = sum(f["stat"][2] for f in group["files"])
        estimate = source_bytes * 4
        if group["kind"] == "video" and group["files"]:
            source = probe(group["files"][0]["path"])
            estimate = max(
                estimate, int(source["duration"] * int(profile["bitrate"]) / 8) * 3
            )
        if shutil.disk_usage(root).free < estimate + 1024**3:
            raise ValueError(
                "Insufficient workspace space: allow estimated temporary output plus 1 GiB reserve"
            )

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
