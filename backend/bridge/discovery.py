import fnmatch
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo
from .legacy import load

PATTERN = re.compile(r"(VID|IMG)_(\d{8}_\d{6})_(00|10)_(\d{3})\.(insv|insp)", re.I)


def stream_count(path):
    return load().count_video_streams(str(path))


def snapshot(path):
    stat = Path(path).stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def hashes(path):
    before = snapshot(path)
    sha = hashlib.sha256()
    sha1 = hashlib.sha1()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
            sha1.update(chunk)
    if snapshot(path) != before:
        raise ValueError("Source changed during hashing")
    return sha.hexdigest(), sha1.hexdigest()


def resolve_original(original_path, mappings):
    original = PurePosixPath(original_path)
    if ".." in original.parts or not original.is_absolute():
        raise ValueError("Unsafe original path")
    for mapping in sorted(
        mappings, key=lambda m: len(PurePosixPath(m["from"]).parts), reverse=True
    ):
        base = PurePosixPath(mapping["from"])
        if original.is_relative_to(base):
            root = Path(mapping["to"]).resolve()
            path = root.joinpath(*original.relative_to(base).parts)
            if not path.resolve().is_relative_to(root):
                raise ValueError("Source path escapes mapping")
            for p in (path, *path.parents):
                if p == root:
                    break
                if p.is_symlink():
                    raise ValueError("Source symlinks are not allowed")
            return path
    raise ValueError("Original path has no configured read-only mapping")


def observe(path, name, scope, asset_id, config, store, now):
    match = PATTERN.fullmatch(name)
    if not match or path.is_symlink() or not path.is_file():
        return None
    stat = snapshot(path)
    key = "observe:" + str(path)
    previous = store.get(key)
    if not previous or previous["stat"] != stat:
        store.set(key, {"stat": stat, "since": now})
        return None
    if now - previous["since"] < config.data["stable_seconds"]:
        return None
    digest = previous.get("sha256")
    sha1 = previous.get("sha1")
    if not digest:
        digest, sha1 = hashes(path)
        store.set(key, {**previous, "sha256": digest, "sha1": sha1})
    prefix, timestamp, role, segment, ext = match.groups()
    return {
        "path": str(path),
        "name": name,
        "scope": scope,
        "asset_id": asset_id,
        "stat": stat,
        "sha256": digest,
        "sha1": sha1,
        "prefix": prefix.upper(),
        "timestamp": timestamp,
        "role": role,
        "segment": segment,
        "kind": "photo" if ext.lower() == "insp" else "video",
    }


def group_files(files, config, store):
    candidates = {}
    groups = {}
    for f in files:
        key = (f["scope"], f["prefix"], f["timestamp"], f["segment"])
        candidates.setdefault(key, {}).setdefault(f["role"], []).append(f)
    for key, roles in candidates.items():
        if "00" not in roles:
            store.event(
                None, "waiting_pair", f"{key[2]} segment {key[3]} missing lens 00"
            )
            continue
        # Identical copies may occur in multiple locations; different bytes with the same
        # logical lens name in an API scope are ambiguous and must not be arbitrarily paired.
        if any(len({f["sha256"] for f in copies}) > 1 for copies in roles.values()):
            store.event(
                None, "conflict", f"{key[2]} segment {key[3]} ambiguous source names"
            )
            continue
        first = roles["00"][0]
        probe_key = "streams:" + first["sha256"]
        streams = store.get(probe_key) if first["kind"] == "video" else 2
        if streams is None and first["kind"] == "video":
            streams = stream_count(first["path"])
            if streams:
                store.set(probe_key, streams)
        if streams is None or streams < 1:
            store.event(None, "unsupported", first["name"])
            continue
        source = [first]
        if streams == 1:
            if "10" not in roles:
                store.event(None, "waiting_pair", first["name"])
                continue
            source.append(roles["10"][0])
        identity = hashlib.sha256(
            json.dumps(
                [(f["role"], f["sha256"]) for f in source]
                + [("segment", first["segment"])]
            ).encode()
        ).hexdigest()
        capture = (
            datetime.strptime(first["timestamp"], "%Y%m%d_%H%M%S")
            .replace(tzinfo=ZoneInfo(config.data["source_timezone"]))
            .isoformat()
        )
        groups[identity] = {
            "id": identity,
            "files": source,
            "timestamp": first["timestamp"],
            "segment": first["segment"],
            "kind": first["kind"],
            "capture_time": capture,
        }
    return list(groups.values())


def discover_folders(config, store, now):
    candidates = []
    for folder in config.data["folders"]:
        root = Path(folder)
        if root.is_symlink() or not root.is_dir():
            raise FileNotFoundError(f"Source mount is unavailable: {root}")
        for directory, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and not Path(directory, d).is_symlink()
                and not any(
                    fnmatch.fnmatch(str(Path(directory, d)), x)
                    for x in config.data["exclusions"]
                )
            ]
            for name in names:
                path = Path(directory, name)
                if name.startswith(".") or any(
                    fnmatch.fnmatch(str(path), x) for x in config.data["exclusions"]
                ):
                    continue
                if PATTERN.fullmatch(name):
                    candidates.append((path, name, str(path.parent), None))
    with ThreadPoolExecutor(max_workers=config.data["scan_parallelism"]) as pool:
        files = list(pool.map(lambda f: observe(*f, config, store, now), candidates))
    return group_files([f for f in files if f], config, store)


def discover_immich(client, config, store, full=False):
    target = store.get("target", client.base)
    watermark = store.get("watermark:" + target)
    # Probe first to obtain a server Date without trusting the execution machine's clock.
    client.search({"originalFileName": {"like": "%.insv"}}, None)
    upper = client.server_time
    if upper is None:
        raise ValueError("Immich did not provide a usable server Date")
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
    lower = watermark - config.data["overlap"] if watermark is not None else None
    index = {} if full else store.get("api-index:" + target, {})
    for suffix in ("insv", "insp"):
        filter = {
            "originalFileName": {"like": "%." + suffix},
            "isOffline": {"eq": False},
            "trashedAt": {"eq": None},
        }
        if lower is not None and not full:
            filter["or"] = [
                {"createdAt": {"gte": iso(lower), "lte": iso(upper)}},
                {"updatedAt": {"gte": iso(lower), "lte": iso(upper)}},
            ]
        else:
            filter["createdAt"] = {"lte": iso(upper)}
        cursor = None
        seen = set()
        while True:
            page = client.search(filter, cursor)
            for asset in page["items"]:
                index[asset["id"]] = asset
            cursor = page.get("nextCursor")
            if not cursor:
                break
            if cursor in seen:
                raise ValueError("Repeated Immich cursor")
            seen.add(cursor)
    store.set("api-index:" + target, index)
    store.set("watermark:" + target, upper)
    files = []
    for asset in index.values():
        name = asset.get("originalFileName", "")
        if not PATTERN.fullmatch(name):
            continue
        if asset.get("isTrashed") or asset.get("isOffline"):
            continue
        if config.data["download_sources"]:
            cache = Path(config.data["work_dir"]) / "sources" / asset["id"]
            cache.mkdir(parents=True, exist_ok=True)
            path = cache / name
            fingerprint = asset.get("checksum")
            if not path.exists() or store.get("download:" + asset["id"]) != fingerprint:
                temp = path.with_suffix(".partial")
                with temp.open("wb") as handle:
                    client.download(asset["id"], handle)
                # Immich internal asset checksums are SHA1 file hashes, base64 encoded.
                if fingerprint and asset.get("checksumAlgorithm", "sha1") == "sha1":
                    import base64

                    _, sha1 = hashes(temp)
                    if fingerprint not in (
                        sha1,
                        base64.b64encode(bytes.fromhex(sha1)).decode(),
                    ):
                        temp.unlink()
                        raise ValueError("Downloaded source checksum differs")
                temp.replace(path)
                store.set("download:" + asset["id"], fingerprint)
        else:
            path = resolve_original(asset["originalPath"], config.data["mappings"])
        if not path.is_file():
            store.event(None, "source_missing", name)
            continue
        f = observe(path, name, "immich:" + target, asset["id"], config, store, upper)
        if f:
            files.append(f)
    return group_files(files, config, store)
