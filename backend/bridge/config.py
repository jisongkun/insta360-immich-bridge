import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

PROFILE = dict(
    output_size="5760x2880",
    bitrate="100000000",
    stitch_type="dynamicstitch",
    auto_resolution=False,
    original_bitrate=False,
    enable_h265=True,
    enable_flowstate=True,
    enable_directionlock=True,
    enable_stitchfusion=True,
    disable_cuda=False,
)
DEFAULTS = dict(
    state_dir="/state",
    work_dir="/work",
    immich_url="",
    api_key_env="IMMICH_API_KEY",
    api_key_file="",
    folders=[],
    mappings=[],
    download_sources=False,
    exclusions=[],
    automatic=False,
    interval=60,
    folder_interval=600,
    stable_seconds=60,
    full_interval=86400,
    overlap=300,
    stitch_parallelism=1,
    scan_parallelism=4,
    deep_scan_parallelism=1,
    thumbnail_parallelism=2,
    sdk_executable="/opt/MediaSDK-3.1.5-linux/bin/MediaSDKTest",
    model_root="/opt/MediaSDK-3.1.5-linux/bin/models/",
    sdk_version="3.1.5",
    replace_shared_links=False,
    replace_stack=False,
    login_token_env="BRIDGE_LOGIN_TOKEN",
    log_max_bytes=10485760,
    log_days=14,
    failure_log_days=30,
    source_timezone="Asia/Shanghai",
    profile=PROFILE,
)


def profile_hash(profile):
    return hashlib.sha256(
        json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class BridgeConfig:
    def __init__(self, data=None, path=None):
        self.data = {**DEFAULTS, **(data or {})}
        self.data["profile"] = {**PROFILE, **self.data["profile"]}
        self.path = Path(path) if path else None
        self._identity_cache = {}

    @classmethod
    def load(cls, path):
        path = Path(path)
        return cls(
            json.loads(path.read_text()) if path.exists() else {}, path
        ).validate()

    def validate(self):
        if set(self.data) - set(DEFAULTS):
            raise ValueError(
                "Unknown settings; store keys in environment/file references"
            )
        for key in (
            "interval",
            "folder_interval",
            "stable_seconds",
            "full_interval",
            "overlap",
            "stitch_parallelism",
            "scan_parallelism",
            "deep_scan_parallelism",
            "thumbnail_parallelism",
            "log_max_bytes",
            "log_days",
            "failure_log_days",
        ):
            value = self.data[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{key} must be a positive integer")
        for key in (
            "stitch_parallelism",
            "scan_parallelism",
            "deep_scan_parallelism",
            "thumbnail_parallelism",
        ):
            if self.data[key] > 64:
                raise ValueError(f"{key} cannot exceed 64")
        for key in (
            "automatic",
            "download_sources",
            "replace_shared_links",
            "replace_stack",
        ):
            if not isinstance(self.data[key], bool):
                raise ValueError(f"{key} must be boolean")
        for key in ("state_dir", "work_dir"):
            if not Path(self.data[key]).is_absolute():
                raise ValueError(f"{key} must be absolute")
        state, work = (Path(self.data[x]).resolve() for x in ("state_dir", "work_dir"))
        if state == work or state.is_relative_to(work) or work.is_relative_to(state):
            raise ValueError("State and work directories must be separate")
        for key in ("folders", "exclusions", "mappings"):
            if not isinstance(self.data[key], list):
                raise ValueError(f"{key} must be a list")
        for root in self.data["folders"]:
            p = Path(root).resolve()
            if not Path(root).is_absolute() or any(
                p == x or p.is_relative_to(x) or x.is_relative_to(p)
                for x in (state, work)
            ):
                raise ValueError(
                    "Source folders must be absolute and separate from work/state"
                )
        for mapping in self.data["mappings"]:
            if set(mapping) != {"from", "to"} or not all(
                Path(mapping[x]).is_absolute() for x in ("from", "to")
            ):
                raise ValueError("Mappings require absolute from/to paths")
            p = Path(mapping["to"]).resolve()
            if any(
                p == x or p.is_relative_to(x) or x.is_relative_to(p)
                for x in (state, work)
            ):
                raise ValueError("Source mappings must be separate from work/state")
        if self.data["immich_url"]:
            url = urlsplit(self.data["immich_url"])
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError("Invalid Immich URL")
        profile = self.data["profile"]
        if set(profile) - set(PROFILE):
            raise ValueError("Unknown stitch settings")
        import re

        if not re.fullmatch(r"\d+x\d+", profile["output_size"]):
            raise ValueError("Invalid output_size")
        w, h = map(int, profile["output_size"].split("x"))
        if h < 2 or w != 2 * h or w % 2 or h % 2:
            raise ValueError("Output must be even 2:1 dimensions")
        if (
            not str(profile["bitrate"]).isdigit()
            or not 0 < int(profile["bitrate"]) < 2147483647
        ):
            raise ValueError("Invalid bitrate")
        if profile["stitch_type"] not in ("optflow", "dynamicstitch", "aistitch"):
            raise ValueError("Unsupported stitch type")
        for key, value in PROFILE.items():
            if isinstance(value, bool) and not isinstance(profile[key], bool):
                raise ValueError(f"{key} must be boolean")
        if profile["enable_directionlock"] and not profile["enable_flowstate"]:
            raise ValueError("Direction lock requires FlowState")
        from zoneinfo import ZoneInfo

        ZoneInfo(self.data["source_timezone"])
        return self

    def changed(self, updates):
        if set(updates) - set(DEFAULTS):
            raise ValueError("Unknown settings")
        data = {**self.data, **updates}
        if "profile" in updates:
            if not isinstance(updates["profile"], dict):
                raise ValueError("Stitch profile must be an object")
            data["profile"] = {**self.data["profile"], **updates["profile"]}
        return BridgeConfig(data, self.path).validate()

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.data, indent=2))
            temp.chmod(0o600)
            temp.replace(self.path)

    def public(self):
        return json.loads(json.dumps(self.data))

    def key(self):
        file = self.data["api_key_file"]
        return (
            Path(file).read_text().strip()
            if file
            else os.getenv(self.data["api_key_env"], "")
        )

    def file_identity(self, path):
        path = Path(path)
        if not path.is_file():
            return "unavailable"
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        cached = self._identity_cache.get(str(path))
        if cached and cached[0] == signature:
            return cached[1]
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        self._identity_cache[str(path)] = (signature, digest.hexdigest())
        return digest.hexdigest()

    def recipe(self):
        models = Path(self.data["model_root"])
        model_identity = (
            profile_hash(
                {
                    str(p.relative_to(models)): self.file_identity(p)
                    for p in sorted(models.rglob("*"))
                    if p.is_file()
                }
            )
            if models.is_dir()
            else "unavailable"
        )
        return {
            **self.data["profile"],
            "sdk_version": self.data["sdk_version"],
            "sdk_executable": self.data["sdk_executable"],
            "sdk_binary_sha256": self.file_identity(self.data["sdk_executable"]),
            "model_root": self.data["model_root"],
            "models_sha256": model_identity,
            "metadata_version": 1,
            "source_timezone": self.data["source_timezone"],
        }
