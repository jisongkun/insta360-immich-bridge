"""Durable delivery phases; only the bridge's verified exports can be replaced."""

import time
from pathlib import Path
from .discovery import hashes, snapshot
from .validation import validate
from .immich import ImmichError
from .converter import Converter


class Pipeline:
    def __init__(self, store, client, converter, config, validator=validate):
        self.store = store
        self.client = client
        self.converter = converter
        self.config = config
        self.validator = validator

    def checkpoint(self, id, phase, **fields):
        self.store.update(id, stage=phase, phase=phase, error=None, **fields)
        self.store.event(id, phase, "Phase persisted")

    def safe_output(self, job):
        path = Path(job["output"])
        root = Path(self.config.data["work_dir"]) / "jobs" / job["id"]
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Output is outside the private job workspace")
        if any(
            path.resolve() == Path(f["path"]).resolve() for f in job["group"]["files"]
        ):
            raise ValueError("Source must never be a cleanup target")
        return path

    @staticmethod
    def check_cancel(cancel):
        if cancel.is_set():
            raise InterruptedError("Task cancelled at a safe boundary")

    def process(self, id, cancel):
        if not self.store.claim(id):
            return
        try:
            self.store.update(id, blocked_by=None)
            self.check_cancel(cancel)
            job = self.store.job(id)
            identity = self.client.identify()
            if self.client.base + "|" + identity["user_id"] != job["target"]:
                raise ValueError("Immich target account changed; delivery blocked")
            self.check_cancel(cancel)
            phase = job.get("phase", "pending")
            if phase in ("pending", "converting"):
                # Refresh only before conversion. Another requested generation may have
                # completed since enqueue; later delivery phases keep their persisted predecessor.
                current = next(
                    (
                        j
                        for j in self.store.jobs()
                        if j["id"] != id
                        and j["source_id"] == job["source_id"]
                        and j["target"] == job["target"]
                        and j["stage"] == "done"
                        and not j.get("replaced_by")
                    ),
                    None,
                )
                if current:
                    previous = {
                        k: current.get(k)
                        for k in (
                            "asset_id",
                            "output_sha256",
                            "output_sha1",
                            "output_bytes",
                            "owned",
                        )
                    }
                    self.store.update(id, previous=previous)
                    job = self.store.job(id)
                if job.get("previous") and not job.get("replace"):
                    raise ValueError(
                        "Existing export: select regenerate/replace explicitly"
                    )
                if cancel.is_set():
                    raise InterruptedError("Task cancelled")
                for f in job["group"]["files"]:
                    if (
                        snapshot(f["path"]) != f["stat"]
                        or hashes(f["path"])[0] != f["sha256"]
                    ):
                        raise ValueError(
                            "Source changed before conversion; discover again"
                        )
                effective = Converter.effective_profile(job["group"], job["profile"])
                Converter.check_space(job["group"], effective, self.config)
                self.store.update(id, effective_profile=effective)
                output = self.converter.convert(
                    id,
                    job["group"],
                    effective,
                    self.config,
                    cancel,
                    lambda stage, fields: self.checkpoint(id, stage, **fields),
                )
                self.checkpoint(id, "validating", output=str(output))
                phase = "validating"
                job = self.store.job(id)
            if phase == "validating":
                output = self.safe_output(job)
                self.validator(
                    output, job["group"], job.get("effective_profile", job["profile"])
                )
                sha256, sha1 = hashes(output)
                self.checkpoint(
                    id,
                    "upload_intent",
                    output_sha256=sha256,
                    output_sha1=sha1,
                    output_bytes=output.stat().st_size,
                )
                phase = "upload_intent"
                job = self.store.job(id)
            if phase == "upload_intent":
                if cancel.is_set():
                    raise InterruptedError("Task cancelled before upload")
                output = self.safe_output(job)
                if hashes(output) != (job["output_sha256"], job["output_sha1"]):
                    raise ValueError("Local export changed before upload")
                result = self.client.find_checksum(job["output_sha1"])
                self.check_cancel(cancel)
                if result is None:
                    result = self.client.upload(
                        output, job["group"]["capture_time"], job["output_sha1"]
                    )
                owned = result["status"] == "created"
                previous = job.get("previous") or {}
                if result["id"] == previous.get("asset_id"):
                    owned = bool(previous.get("owned"))
                self.checkpoint(id, "verifying", asset_id=result["id"], owned=owned)
                phase = "verifying"
                job = self.store.job(id)
            if phase == "verifying":
                self.check_cancel(cancel)
                if self.client.asset(job["asset_id"]).get("isTrashed"):
                    raise ValueError("Export is in Immich trash")
                self.check_cancel(cancel)
                digest = self.client.download(
                    job["asset_id"], None, max_bytes=job["output_bytes"]
                )
                if digest != job["output_sha256"]:
                    raise ValueError(
                        "Server original hash differs; local export retained"
                    )
                # Receipt precedes all association changes and local deletion.
                self.checkpoint(id, "replacing", verified=True)
                phase = "replacing"
                job = self.store.job(id)
            if phase == "replacing":
                self.check_cancel(cancel)
                previous = job.get("previous")
                if previous and previous.get("asset_id") != job["asset_id"]:
                    if (
                        not job.get("replace")
                        or not job["owned"]
                        or not previous.get("owned")
                    ):
                        raise ValueError(
                            "Replacement requires proof that both exports belong to this bridge"
                        )
                    old = previous["asset_id"]
                    if old in {f.get("asset_id") for f in job["group"]["files"]}:
                        raise ValueError("Original asset cannot be replaced")
                    try:
                        state = self.client.asset(old)
                    except ImmichError as error:
                        if error.status != 404:
                            raise
                        state = {"isTrashed": True}
                        self.store.event(
                            id,
                            "previous_missing",
                            "Previous export is missing; explicit regeneration continues without mutation",
                        )
                    self.check_cancel(cancel)
                    if not state.get("isTrashed"):
                        digest = self.client.download(
                            old, None, max_bytes=previous.get("output_bytes")
                        )
                        if digest != previous["output_sha256"]:
                            raise ValueError(
                                "Previous export changed; replacement stopped"
                            )
                        self.check_cancel(cancel)
                        if not job.get("copied"):
                            self.client.copy(
                                old,
                                job["asset_id"],
                                job.get(
                                    "copy_options",
                                    {
                                        "albums": True,
                                        "favorite": True,
                                        "sidecar": False,
                                        "sharedLinks": False,
                                        "stack": False,
                                    },
                                ),
                            )
                            self.store.update(id, copied=True)
                        # Readback on resume resolves an uncertain trash response.
                        self.check_cancel(cancel)
                        self.client.trash(old)
                        if not self.client.asset(old).get("isTrashed"):
                            raise ValueError(
                                "Immich has not confirmed previous export trash"
                            )
                    for prior in self.store.jobs():
                        if (
                            prior["source_id"] == job["source_id"]
                            and prior["target"] == job["target"]
                            and prior.get("asset_id") == old
                        ):
                            self.store.update(prior["id"], replaced_by=id)
                self.check_cancel(cancel)
                self.checkpoint(id, "cleanup")
                phase = "cleanup"
                job = self.store.job(id)
            if phase == "cleanup":
                self.check_cancel(cancel)
                if not job.get("verified"):
                    raise ValueError("Cannot clean unverified output")
                output = self.safe_output(job)
                if output.exists():
                    if hashes(output)[0] != job["output_sha256"]:
                        raise ValueError("Local output changed; cleanup stopped")
                    output.unlink()
                self.checkpoint(id, "done", local_deleted=True, pid=None)
        except InterruptedError as error:
            self.store.update(id, stage="cancelled", error=str(error), pid=None)
            self.store.event(id, "cancelled", str(error))
        except Exception as error:
            # API errors are already sanitized. Do not log response bodies or credentials.
            message = (
                str(error)
                if isinstance(error, (ValueError, RuntimeError))
                else type(error).__name__
            )
            key = self.config.key()
            if key:
                message = message.replace(key, "[redacted]")
            attempts = self.store.job(id).get("attempts", 0) + 1
            self.store.update(
                id,
                stage="failed",
                error=message,
                pid=None,
                attempts=attempts,
                retryable=bool(getattr(error, "retryable", False)),
                retry_at=time.time()
                + min(self.config.data["interval"] * 2 ** min(attempts, 10), 3600),
                http_status=getattr(error, "status", None),
            )
            self.store.event(id, "failed", message)
        finally:
            self.store.update(id, claimed=0)
