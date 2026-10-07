"""One scheduler owner, explicit manual work and read-only legacy preview helpers."""

import fcntl
import logging
import os
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from .store import Store
from .immich import ImmichClient, ImmichError
from .discovery import discover_folders, discover_immich
from .converter import Converter
from .pipeline import Pipeline
from .legacy import load

ACTIONS = {
    "scan",
    "deep_scan",
    "stitch",
    "full_stitch",
    "full_run",
    "generate_thumbnails",
    "stitch_selected",
    "regenerate_selected",
    "test_connection",
}


class Service:
    def __init__(self, config):
        self.config = config
        self.guard = threading.RLock()
        self.stop = threading.Event()
        self.active_tasks = {}
        self.cancels = {}
        state = Path(config.data["state_dir"])
        state.mkdir(parents=True, exist_ok=True)
        self.lock = (state / "owner.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("Another bridge owns this state directory") from None
        self.store = Store(state / "bridge.db")
        self.store.recover()
        self.log = logging.getLogger("bridge." + str(uuid.uuid4()))
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        logs = state / "logs"
        logs.mkdir(exist_ok=True)
        handler = RotatingFileHandler(
            logs / "bridge.log", maxBytes=config.data["log_max_bytes"], backupCount=5
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self.log.addHandler(handler)
        self.connection = self.store.get("connection", {})
        self.thread = None

    def event(self, stage, message):
        key = self.config.key()
        token = os.getenv(self.config.data["login_token_env"], "")
        for secret in (key, token):
            if secret:
                message = message.replace(secret, "[redacted]")
        self.store.event(None, stage, message)
        self.log.info("%s %s", stage, message)

    def client(self):
        if not self.config.data["immich_url"] or not self.config.key():
            raise ValueError("Configure Immich URL and API key reference first")
        return ImmichClient(self.config.data["immich_url"], self.config.key())

    def connect(self):
        client = self.client()
        identity = client.identify()
        target = client.base + "|" + identity["user_id"]
        self.store.set("target", target)
        self.connection = {**identity, "ok": True, "checked_at": time.time()}
        self.store.set("connection", self.connection)
        self.store.set("api_paused", False)
        return client, target

    def configure(self, updates):
        with self.guard:
            if {"state_dir", "work_dir"} & set(updates):
                raise ValueError(
                    "State/work directories require restart and config-file editing"
                )
            config = self.config.changed(updates)
            config.save()
            self.config = config
        return config.public()

    def scan(self, full=False, folders=True, api=True):
        config = self.config
        groups = []
        now = time.time()
        if api:
            self.store.set("last_api_attempt", now)
        if folders:
            self.store.set("last_folder_attempt", now)
        if full:
            self.store.set("last_full_attempt", now)
        if api and config.data["immich_url"]:
            client, target = self.connect()
            groups += discover_immich(client, config, self.store, full)
            self.store.set("last_api_scan", time.time())
            if full:
                self.store.set("last_full_scan", time.time())
        if folders and config.data["folders"]:
            groups += discover_folders(
                config.changed(
                    {"scan_parallelism": config.data["deep_scan_parallelism"]}
                )
                if full
                else config,
                self.store,
                time.time(),
            )
            self.store.set("last_folder_scan", time.time())
        target = self.store.get("target")
        # Folder discovery can run without credentials, but do not scope receipts to an unknown account.
        if groups and not target:
            raise ValueError("Test Immich connection before queueing source groups")
        recipe = config.recipe()
        for group in groups:
            self.store.enqueue(group, recipe, target)
        self.store.set(
            "scan_summary", {"groups": len(groups), "at": time.time(), "full": full}
        )
        self.event(
            "discovered",
            f"{len(groups)} stable source groups; completed receipts retained",
        )
        if full:
            self.reconcile()

    def reconcile(self):
        if not self.config.data["immich_url"]:
            return
        client, target = self.connect()

        def check(job):
            if (
                job["stage"] == "done"
                and job["target"] == target
                and not job.get("replaced_by")
            ):
                try:
                    missing = (
                        ImmichClient(client.base, self.config.key())
                        .asset(job["asset_id"])
                        .get("isTrashed", False)
                    )
                except ImmichError as error:
                    if error.status == 404:
                        missing = True
                    else:
                        raise
                self.store.update(job["id"], remote_missing=missing)

        with ThreadPoolExecutor(
            max_workers=self.config.data["deep_scan_parallelism"]
        ) as pool:
            list(pool.map(check, self.store.jobs()))
        # A missing remote receipt is displayed and requires explicit regeneration, never automatic reset.

    def regenerate(self, ids):
        jobs = [self.store.job(id) for id in ids]
        if not jobs:
            raise ValueError("Select completed exports")
        for job in jobs:
            if (
                job["stage"] != "done"
                or not job.get("verified")
                or not job.get("owned")
                or job.get("replaced_by")
            ):
                raise ValueError("Select current verified exports owned by this bridge")
        result = []
        for job in jobs:
            from zoneinfo import ZoneInfo

            group = {
                **job["group"],
                "capture_time": datetime.strptime(
                    job["group"]["timestamp"], "%Y%m%d_%H%M%S"
                )
                .replace(tzinfo=ZoneInfo(self.config.data["source_timezone"]))
                .isoformat(),
            }
            new = self.store.enqueue(
                group, self.config.recipe(), job["target"], force=True
            )
            self.store.update(
                new,
                replace=True,
                run_requested=True,
                copy_options={
                    "albums": True,
                    "favorite": True,
                    "sidecar": False,
                    "sharedLinks": self.config.data["replace_shared_links"],
                    "stack": self.config.data["replace_stack"],
                },
            )
            result.append(new)
        return result

    def run_jobs(self, ids=None, retry=False, cancel=None):
        client, target = self.connect()
        config = self.config
        cancel = cancel or threading.Event()
        jobs = [self.store.job(id) for id in ids] if ids else self.store.jobs()
        eligible = []
        for job in reversed(jobs):
            if job["target"] != target or job["stage"] == "done":
                continue
            if job["stage"] in ("failed", "cancelled") and not retry:
                continue
            if job.get("previous") and not job.get("replace"):
                continue
            if job["stage"] == "cancelled":
                self.store.update(job["id"], stage="pending")
            self.store.update(job["id"], run_requested=True)
            eligible.append(job["id"])

        def work(id):
            # Sessions are not shared across threads; keys rotate between work submissions.
            Pipeline(
                self.store, ImmichClient(client.base, config.key()), Converter(), config
            ).process(id, cancel)

        with ThreadPoolExecutor(max_workers=config.data["stitch_parallelism"]) as pool:
            list(pool.map(work, eligible))

    def thumbnails(self, ids=None):
        legacy = load()
        root = Path(self.config.data["state_dir"]) / "thumbnails"
        root.mkdir(exist_ok=True)
        jobs = [self.store.job(id) for id in ids] if ids else self.store.jobs()

        def make(job):
            files = job["group"]["files"]
            if not files:
                return
            path = root / (job["id"] + ".jpg")
            if path.exists():
                return
            source = files[0]["path"]
            duration = legacy.video_duration_seconds(source) or 0
            ok = legacy.extract_thumbnail(source, str(path), duration / 2)
            self.store.event(
                job["id"],
                "thumbnail",
                "Preview saved" if ok else "Preview extraction failed",
            )

        with ThreadPoolExecutor(
            max_workers=self.config.data["thumbnail_parallelism"]
        ) as pool:
            list(pool.map(make, jobs))

    def submit(self, action, ids=None):
        if action not in ACTIONS:
            raise ValueError("Invalid action")
        if ids is not None and (
            not isinstance(ids, list) or any(not isinstance(x, str) for x in ids)
        ):
            raise ValueError("Invalid job IDs")
        if action in ("stitch_selected", "regenerate_selected") and not ids:
            raise ValueError("Select jobs first")
        # Validate IDs before dispatch so clients receive a concrete 404.
        if ids:
            for id in ids:
                self.store.job(id)
        key = (
            "scan"
            if action in ("scan", "deep_scan")
            else "run"
            if action
            in (
                "stitch",
                "full_stitch",
                "stitch_selected",
                "regenerate_selected",
                "full_run",
            )
            else action
        )
        with self.guard:
            for id, t in self.active_tasks.items():
                if t["key"] == key:
                    return id
            if action == "full_run" and any(
                t["key"] == "scan" for t in self.active_tasks.values()
            ):
                raise ValueError(
                    "A discovery is already running; retry full run after it finishes"
                )
            if key == "scan" and any(
                t["action"] == "full_run" for t in self.active_tasks.values()
            ):
                return next(
                    id
                    for id, t in self.active_tasks.items()
                    if t["action"] == "full_run"
                )
            if action == "regenerate_selected":
                ids = self.regenerate(ids)
            id = str(uuid.uuid4())
            cancel = threading.Event()
            self.cancels[id] = cancel
            self.active_tasks[id] = {
                "id": id,
                "action": action,
                "key": key,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }

            def execute():
                try:
                    if action == "test_connection":
                        self.connect()
                        self.event("connection", "Connection verified")
                    elif action in ("scan", "deep_scan", "full_run"):
                        self.scan(full=action == "deep_scan")
                        if action == "full_run" and not cancel.is_set():
                            self.run_jobs(cancel=cancel)
                    elif action == "generate_thumbnails":
                        self.thumbnails(ids)
                    else:
                        self.run_jobs(
                            ids,
                            retry=action
                            in (
                                "full_stitch",
                                "stitch_selected",
                                "regenerate_selected",
                            ),
                            cancel=cancel,
                        )
                except Exception as error:
                    self.connection = {
                        "ok": False,
                        "error": str(error)
                        if isinstance(error, (ValueError, ImmichError))
                        else type(error).__name__,
                    }
                    if isinstance(error, ImmichError) and error.status in (401, 403):
                        self.store.set("api_paused", True)
                    self.store.set("connection", self.connection)
                    self.event("task_failed", self.connection["error"])
                finally:
                    with self.guard:
                        self.active_tasks.pop(id, None)
                        self.cancels.pop(id, None)

            worker = threading.Thread(target=execute, name="bridge-task", daemon=True)
            self.active_tasks[id]["thread"] = worker
            worker.start()
            return id

    def cancel(self, id):
        with self.guard:
            if id not in self.cancels:
                raise KeyError(id)
            self.cancels[id].set()
        self.event(
            "cancel_requested", "Active operation will stop at its next safe boundary"
        )

    def tick(self, now):
        if not self.config.data["automatic"] or self.store.get("api_paused", False):
            return
        with self.guard:
            if self.active_tasks:
                return
        full = (
            bool(self.config.data["immich_url"])
            and now - self.store.get("last_full_attempt", 0)
            >= self.config.data["full_interval"]
        )
        api = (
            bool(self.config.data["immich_url"])
            and now - self.store.get("last_api_attempt", 0)
            >= self.config.data["interval"]
        )
        folder = (
            bool(self.config.data["folders"])
            and now - self.store.get("last_folder_attempt", 0)
            >= self.config.data["folder_interval"]
        )
        retries = [
            j["id"]
            for j in self.store.jobs()
            if j["stage"] == "failed"
            and j.get("retryable")
            and now >= j.get("retry_at", 0)
        ]
        if full or api or folder or retries:
            # One automatic task owns both discovery and dispatch; optional intervals stay independent.
            id = "automatic"
            cancel = threading.Event()

            def run():
                since = time.time()
                try:
                    if full or api or folder:
                        self.scan(full, folders=folder, api=api or full)
                    if not cancel.is_set():
                        self.run_jobs(cancel=cancel)
                        if retries:
                            self.run_jobs(retries, retry=True, cancel=cancel)
                    if any(
                        j.get("http_status") in (401, 403)
                        for j in self.store.jobs()
                        if j["stage"] == "failed" and j["updated"] >= since
                    ):
                        self.store.set("api_paused", True)
                except Exception as error:
                    if isinstance(error, ImmichError) and error.status in (401, 403):
                        self.store.set("api_paused", True)
                    self.connection = {
                        "ok": False,
                        "error": str(error)
                        if isinstance(error, (ValueError, ImmichError))
                        else type(error).__name__,
                    }
                    self.store.set("connection", self.connection)
                    self.event("automatic_failed", self.connection["error"])
                finally:
                    with self.guard:
                        self.active_tasks.pop(id, None)
                        self.cancels.pop(id, None)

            with self.guard:
                self.active_tasks[id] = {
                    "id": id,
                    "action": "full_run",
                    "key": "run",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }
                self.cancels[id] = cancel
                worker = threading.Thread(target=run, daemon=True)
                self.active_tasks[id]["thread"] = worker
                worker.start()

    def maintain_logs(self, now):
        root = Path(self.config.data["work_dir"]) / "jobs"
        for job in self.store.jobs():
            if job["claimed"]:
                continue
            days = (
                self.config.data["log_days"]
                if job["stage"] == "done"
                else self.config.data["failure_log_days"]
            )
            job_root = root / job["id"]
            for path in job_root.rglob("*.log"):
                if path.is_symlink() or not path.resolve().is_relative_to(
                    job_root.resolve()
                ):
                    continue
                if path.stat().st_mtime < now - days * 86400:
                    path.unlink()
        with self.store.connection() as c:
            c.execute(
                "DELETE FROM events WHERE at<?",
                (now - self.config.data["failure_log_days"] * 86400,),
            )
        self.store.set("last_log_cleanup", now)

    def start(self):
        # Resume only work previously requested, including delivery after local output cleanup.
        if any(
            j.get("run_requested") and j["stage"] not in ("done", "failed", "cancelled")
            for j in self.store.jobs()
        ):
            self.submit("stitch")

        def loop():
            while not self.stop.wait(1):
                try:
                    now = time.time()
                    self.tick(now)
                    if now - self.store.get("last_log_cleanup", 0) > 86400:
                        self.maintain_logs(now)
                except Exception as error:
                    self.event("scheduler_failed", type(error).__name__)

        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()

    def close(self):
        if self.lock.closed:
            return
        self.stop.set()
        with self.guard:
            tasks = list(self.active_tasks.values())
            [e.set() for e in self.cancels.values()]
        for t in tasks:
            t["thread"].join(timeout=15)
        if self.thread:
            self.thread.join(timeout=2)
        if any(t["thread"].is_alive() for t in tasks):
            return  # keep the ownership lock until process exit
        for handler in list(self.log.handlers):
            handler.close()
            self.log.removeHandler(handler)
        self.lock.close()

    def status(self):
        jobs = []
        ratio = self.store.get("expected_ratio", 1)
        for j in self.store.jobs():
            stage = j["stage"]
            done = stage == "done"
            active = bool(j["claimed"])
            status = (
                "processed"
                if done
                else "processing"
                if active
                else "failed"
                if stage in ("failed", "cancelled")
                else "unprocessed"
            )
            size = j.get("output_bytes", 0)
            progress = 1 if done else 0
            pid = j.get("pid")
            if active and j.get("work_dir"):
                database = Path(j["work_dir"]) / "conversion.db"
                if database.is_file():
                    try:
                        with sqlite3.connect(
                            f"file:{database}?mode=ro", uri=True, timeout=1
                        ) as c:
                            row = c.execute(
                                "SELECT stitched_size,expected_size,process,pid FROM jobs LIMIT 1"
                            ).fetchone()
                        if row:
                            size, _, progress, worker_pid = row
                            progress = min(progress or 0, 0.98)
                            pid = worker_pid or pid
                    except sqlite3.Error:
                        pass
            expected = int(sum(f["stat"][2] for f in j["group"]["files"]) * ratio)
            jobs.append(
                dict(
                    id=j["id"],
                    timestamp=j["group"]["capture_time"],
                    final_file=j.get(
                        "output",
                        j["id"] + (".jpg" if j["group"]["kind"] == "photo" else ".mp4"),
                    ),
                    source_files=[f["path"] for f in j["group"]["files"]],
                    status=status,
                    stage=stage,
                    phase=j.get("phase", stage),
                    queue_state="queued" if status == "unprocessed" else None,
                    pid=pid,
                    stitched_size=size,
                    process=progress,
                    expected_size=expected,
                    created_at=datetime.fromtimestamp(
                        j["created"], timezone.utc
                    ).isoformat(),
                    updated_at=datetime.fromtimestamp(
                        j["updated"], timezone.utc
                    ).isoformat(),
                    thumbnail_url=f"/thumbnails/{j['id']}.jpg"
                    if (
                        Path(self.config.data["state_dir"])
                        / "thumbnails"
                        / (j["id"] + ".jpg")
                    ).exists()
                    else None,
                    asset_id=j.get("asset_id"),
                    verified=j.get("verified", False),
                    owned=j.get("owned", False),
                    error=j.get("error"),
                    remote_missing=j.get("remote_missing", False),
                    replaced_by=j.get("replaced_by"),
                    recipe=j["recipe"],
                    local_deleted=j.get("local_deleted", False),
                )
            )
        with self.guard:
            tasks = [
                {k: v for k, v in t.items() if k not in ("thread", "key")}
                for t in self.active_tasks.values()
            ]
        return dict(
            jobs=jobs,
            active_jobs=[j["id"] for j in jobs if j["status"] == "processing"],
            active_tasks=tasks,
            pending_jobs=sum(j["status"] == "unprocessed" for j in jobs),
            queued_jobs=sum(j["status"] == "unprocessed" for j in jobs),
            max_parallel_jobs=self.config.data["stitch_parallelism"],
            expected_size_ratio=ratio,
            stitch_settings=self.config.data["profile"],
            concurrency={
                "stitch": self.config.data["stitch_parallelism"],
                "scan": self.config.data["scan_parallelism"],
                "deep_scan": self.config.data["deep_scan_parallelism"],
                "thumbnails": self.config.data["thumbnail_parallelism"],
            },
            connection=self.connection,
            api_paused=self.store.get("api_paused", False),
            scan_summary=self.store.get("scan_summary", {}),
            automatic=self.config.data["automatic"],
            next_api_scan=max(
                time.time(),
                self.store.get("last_api_attempt", 0) + self.config.data["interval"],
            )
            if self.config.data["automatic"] and self.config.data["immich_url"]
            else None,
            next_folder_scan=max(
                time.time(),
                self.store.get("last_folder_attempt", 0)
                + self.config.data["folder_interval"],
            )
            if self.config.data["automatic"] and self.config.data["folders"]
            else None,
        )
