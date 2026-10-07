import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from .config import profile_hash


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as c:
            version = c.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValueError(
                    "State schema is newer than this bridge; do not downgrade"
                )
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript("""
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, source_id TEXT, recipe TEXT,
              target TEXT, stage TEXT, claimed INTEGER DEFAULT 0, payload TEXT, created REAL, updated REAL);
            CREATE INDEX IF NOT EXISTS jobs_identity ON jobs(source_id,recipe,target);
            CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT,stage TEXT,message TEXT,at REAL);
            PRAGMA user_version=1;
            """)

    @contextmanager
    def connection(self):
        with sqlite3.connect(self.path, timeout=30) as c:
            c.row_factory = sqlite3.Row
            yield c

    def enqueue(self, group, profile, target, force=False):
        recipe = profile_hash(profile)
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            if not force:
                row = c.execute(
                    "SELECT id,claimed,payload FROM jobs WHERE source_id=? AND recipe=? AND target=? ORDER BY created DESC LIMIT 1",
                    (group["id"], recipe, target),
                ).fetchone()
                if row and not json.loads(row["payload"]).get("replaced_by"):
                    existing = json.loads(
                        c.execute(
                            "SELECT payload FROM jobs WHERE id=?", (row["id"],)
                        ).fetchone()[0]
                    )
                    if not row["claimed"]:
                        existing["group"] = group
                    c.execute(
                        "UPDATE jobs SET payload=? WHERE id=?",
                        (json.dumps(existing), row["id"]),
                    )
                    return row["id"]
            previous = c.execute(
                "SELECT payload FROM jobs WHERE source_id=? AND target=? AND stage='done' ORDER BY created DESC LIMIT 1",
                (group["id"], target),
            ).fetchone()
            payload = dict(group=group, profile=profile, verified=False, owned=False)
            if previous:
                p = json.loads(previous[0])
                payload["previous"] = {
                    k: p.get(k)
                    for k in (
                        "asset_id",
                        "output_sha256",
                        "output_sha1",
                        "output_bytes",
                        "owned",
                    )
                }
            job_id = str(uuid.uuid4())
            c.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,0,?,?,?)",
                (
                    job_id,
                    group["id"],
                    recipe,
                    target,
                    "pending",
                    json.dumps(payload),
                    time.time(),
                    time.time(),
                ),
            )
            return job_id

    def job(self, job_id):
        with self.connection() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            return {**dict(row), **json.loads(row["payload"])}

    def jobs(self):
        with self.connection() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM jobs ORDER BY created DESC")]
        return [self.job(i) for i in ids]

    def claim(self, job_id):
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            job = c.execute(
                "SELECT source_id,target FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if (
                job
                and c.execute(
                    "SELECT 1 FROM jobs WHERE source_id=? AND target=? AND claimed=1",
                    (job["source_id"], job["target"]),
                ).fetchone()
            ):
                return False
            if job:
                unfinished = c.execute(
                    "SELECT id,payload FROM jobs WHERE source_id=? AND target=? AND id!=? AND stage!='done'",
                    (job["source_id"], job["target"], job_id),
                ).fetchall()
                # An unresolved remote delivery retains the source lineage across failure,
                # cancellation and restart. Resume it before another export can take over.
                blockers = [
                    r["id"]
                    for r in unfinished
                    if json.loads(r["payload"]).get("phase", "pending")
                    in ("upload_intent", "verifying", "replacing", "cleanup")
                ]
                if blockers:
                    row = c.execute(
                        "SELECT payload FROM jobs WHERE id=?", (job_id,)
                    ).fetchone()
                    payload = json.loads(row[0])
                    if payload.get("blocked_by") != blockers[0]:
                        payload["blocked_by"] = blockers[0]
                        c.execute(
                            "UPDATE jobs SET payload=? WHERE id=?",
                            (json.dumps(payload), job_id),
                        )
                        c.execute(
                            "INSERT INTO events(job_id,stage,message,at) VALUES(?,?,?,?)",
                            (
                                job_id,
                                "blocked",
                                "Resume unfinished generation " + blockers[0],
                                time.time(),
                            ),
                        )
                    return False
            return (
                c.execute(
                    "UPDATE jobs SET claimed=1 WHERE id=? AND claimed=0 AND stage NOT IN ('done','cancelled')",
                    (job_id,),
                ).rowcount
                == 1
            )

    def update(self, job_id, **fields):
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT payload,stage,claimed FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row:
                raise KeyError(job_id)
            payload = json.loads(row[0])
            stage = fields.pop("stage", row[1])
            claimed = fields.pop("claimed", row[2])
            payload.update(fields)
            c.execute(
                "UPDATE jobs SET payload=?,stage=?,claimed=?,updated=? WHERE id=?",
                (json.dumps(payload), stage, claimed, time.time(), job_id),
            )

    def recover(self):
        with self.connection() as c:
            c.execute("UPDATE jobs SET claimed=0")

    def get(self, key, default=None):
        with self.connection() as c:
            row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.connection() as c:
            c.execute(
                "INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def event(self, job_id, stage, message):
        with self.connection() as c:
            c.execute(
                "INSERT INTO events(job_id,stage,message,at) VALUES(?,?,?,?)",
                (job_id, stage, str(message), time.time()),
            )

    def events(self, job_id, after=0):
        with self.connection() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM events WHERE job_id IS ? AND seq>? ORDER BY seq LIMIT 500",
                    (job_id, after),
                )
            ]

    def recent_events(self, job_id):
        with self.connection() as c:
            rows = c.execute(
                "SELECT * FROM events WHERE job_id IS ? ORDER BY seq DESC LIMIT 500",
                (job_id,),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]
