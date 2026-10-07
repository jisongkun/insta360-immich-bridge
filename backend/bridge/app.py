import hmac
import math
import os
from pathlib import Path
from flask import Flask, jsonify, request, send_file


def create_app(service):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

    def valid(token):
        expected = os.getenv(service.config.data["login_token_env"], "")
        return bool(
            expected
            and isinstance(token, str)
            and hmac.compare_digest(token.encode(), expected.encode())
        )

    @app.before_request
    def authenticate():
        if request.path != "/login" and not valid(
            request.headers.get("Authorization", "").removeprefix("Bearer ")
        ):
            return jsonify(error="Login required"), 401

    @app.errorhandler(ValueError)
    def bad(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(KeyError)
    def missing(error):
        return jsonify(error="Job/task not found"), 404

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError("Expected JSON object")
        return value

    @app.post("/login")
    def login():
        return (
            (jsonify(ok=True), 200)
            if valid(body().get("token"))
            else (jsonify(error="Invalid token"), 401)
        )

    @app.get("/status")
    def status():
        return jsonify(service.status())

    @app.route("/settings/bridge", methods=["GET", "POST"])
    def config():
        return jsonify(
            service.config.public()
            if request.method == "GET"
            else service.configure(body())
        )

    @app.post("/settings/stitch")
    def stitch():
        update = body()
        profile = {**service.config.data["profile"], **update}
        if profile.get("auto_resolution") and not profile.get("output_size"):
            profile["output_size"] = service.config.data["profile"]["output_size"]
        if profile.get("original_bitrate") and not profile.get("bitrate"):
            profile["bitrate"] = service.config.data["profile"]["bitrate"]
        service.configure({"profile": profile})
        return jsonify(profile)

    @app.post("/settings/parallelism")
    def parallelism():
        update = body()
        if set(update) - {
            "stitch_parallelism",
            "scan_parallelism",
            "deep_scan_parallelism",
            "thumbnail_parallelism",
        }:
            raise ValueError("Unknown parallelism")
        service.configure(update)
        return jsonify(update)

    @app.post("/settings/ratio")
    def ratio():
        value = body().get("expected_size_ratio")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError("Invalid estimated size ratio")
        service.store.set("expected_ratio", value)
        return jsonify(expected_size_ratio=value)

    @app.post("/settings/ratio/compute")
    def compute():
        rows = [
            j
            for j in service.store.jobs()
            if j.get("verified") and j.get("output_bytes")
        ]
        raw = sum(sum(f["stat"][2] for f in j["group"]["files"]) for j in rows)
        if not raw:
            raise ValueError("No verified export sizes available yet")
        value = sum(j["output_bytes"] for j in rows) / raw
        service.store.set("expected_ratio", value)
        return jsonify(expected_size_ratio=value)

    @app.post("/tasks")
    def tasks():
        value = body()
        action = value.get("action")
        id = service.submit(action, value.get("job_ids"))
        return jsonify(scheduled=action, task_id=id)

    @app.post("/tasks/terminate")
    def terminate():
        id = body().get("task_id")
        service.cancel(id)
        return jsonify(terminated=id)

    @app.get("/jobs/<id>/events")
    def events(id):
        service.store.job(id)
        try:
            after = int(request.args.get("after", 0))
        except ValueError:
            raise ValueError("Invalid event cursor") from None
        return jsonify(
            events=service.store.events(id, after)
            if "after" in request.args
            else service.store.recent_events(id)
        )

    @app.get("/events")
    def global_events():
        try:
            after = int(request.args.get("after", 0))
        except ValueError:
            raise ValueError("Invalid event cursor") from None
        return jsonify(
            events=service.store.events(None, after)
            if "after" in request.args
            else service.store.recent_events(None)
        )

    @app.get("/jobs/<id>/details")
    def details(id):
        job = service.store.job(id)
        return jsonify(
            profile=job["profile"],
            group=job["group"],
            target=job["target"],
            recipe=job["recipe"],
            previous=job.get("previous"),
            effective_profile=job.get("effective_profile"),
            blocked_by=job.get("blocked_by"),
        )

    @app.get("/jobs/<id>/logs")
    def logs(id):
        job = service.store.job(id)
        root = Path(service.config.data["work_dir"]) / "jobs" / id
        parts = []
        if root.exists():
            for path in sorted(root.rglob("*.log"))[-10:]:
                if path.is_symlink() or not path.resolve().is_relative_to(
                    root.resolve()
                ):
                    continue
                with path.open("rb") as handle:
                    handle.seek(max(0, path.stat().st_size - 65536))
                    data = handle.read(65536).decode(errors="replace")
                parts.append({"name": str(path.relative_to(root)), "text": data})
        for part in parts:
            for secret in (
                service.config.key(),
                os.getenv(service.config.data["login_token_env"], ""),
            ):
                if secret:
                    part["text"] = part["text"].replace(secret, "[redacted]")
        return jsonify(
            logs=parts,
            stage=job["stage"],
            phase=job.get("phase"),
            error=job.get("error"),
        )

    @app.get("/thumbnails/<id>.jpg")
    def thumbnail(id):
        service.store.job(id)
        path = Path(service.config.data["state_dir"]) / "thumbnails" / (id + ".jpg")
        if not path.is_file() or path.is_symlink():
            raise KeyError(id)
        return send_file(path, mimetype="image/jpeg")

    return app
