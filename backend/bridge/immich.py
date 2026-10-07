import hashlib
import re
from email.utils import parsedate_to_datetime
from pathlib import Path
import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder


class ImmichError(RuntimeError):
    def __init__(self, status=0):
        self.status = status
        self.retryable = status == 0 or status == 429 or status >= 500
        super().__init__(
            f"Immich request failed ({status or 'network'}); response body omitted"
        )


class ImmichClient:
    def __init__(self, base_url, api_key, timeout=120):
        self.base = base_url.rstrip("/")
        if not self.base.endswith("/api"):
            self.base += "/api"
        self.key = api_key
        self.timeout = timeout
        self.server_time = None
        self.session = requests.Session()
        self.session.trust_env = False

    def request(self, method, path, **kwargs):
        headers = {"x-api-key": self.key, **kwargs.pop("headers", {})}
        try:
            response = self.session.request(
                method,
                self.base + path,
                headers=headers,
                timeout=(15, self.timeout),
                allow_redirects=False,
                **kwargs,
            )
        except requests.RequestException:
            raise ImmichError() from None
        if not 200 <= response.status_code < 300:
            status = response.status_code
            response.close()
            raise ImmichError(status)
        try:
            date = response.headers.get("Date")
            if date:
                self.server_time = parsedate_to_datetime(
                    date.split("GMT")[0] + "GMT"
                ).timestamp()
        except (ValueError, TypeError):
            pass
        return response

    def json(self, method, path, **kwargs):
        with self.request(method, path, **kwargs) as r:
            if r.status_code == 204 or not r.content:
                return {}
            try:
                return r.json()
            except ValueError:
                raise ImmichError(502) from None

    def identify(self):
        user = self.json("GET", "/users/me")
        about = self.json("GET", "/server/about")
        if not user.get("id"):
            raise ImmichError(502)
        version = about.get("version", "unknown")
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
        if not match or int(match[1]) != 3 or int(match[2]) < 2:
            raise ValueError(
                "Bridge requires tested Immich 3.2 API shape; check server compatibility"
            )
        return {"user_id": user["id"], "server": self.base, "version": version}

    def search(self, filter, cursor=None):
        body = {
            "filter": filter,
            "size": 250,
            "orderBy": {"field": "fileCreatedAt", "direction": "asc"},
        }
        if cursor:
            body["cursor"] = cursor
        return self.json("POST", "/search/metadata", json=body)["assets"]

    def find_checksum(self, sha1):
        result = self.json(
            "POST",
            "/assets/bulk-upload-check",
            json={"assets": [{"id": "bridge", "checksum": sha1}]},
        )
        for item in result["results"]:
            if item.get("reason") == "duplicate":
                if item.get("isTrashed"):
                    raise ValueError(
                        "Matching export is in Immich trash; restore or resolve it before delivery"
                    )
                return {"id": item["assetId"], "status": "duplicate"}
        return None

    def upload(self, path, capture_time, sha1):
        with Path(path).open("rb") as handle:
            encoder = MultipartEncoder(
                fields={
                    "assetData": (Path(path).name, handle, "application/octet-stream"),
                    "fileCreatedAt": capture_time,
                    "fileModifiedAt": capture_time,
                }
            )
            return self.json(
                "POST",
                "/assets",
                data=encoder,
                headers={
                    "Content-Type": encoder.content_type,
                    "x-immich-checksum": sha1,
                },
            )

    def asset(self, asset_id):
        return self.json("GET", f"/assets/{asset_id}")

    def download(self, asset_id, destination, max_bytes=None):
        digest = hashlib.sha256()
        count = 0
        with self.request(
            "GET", f"/assets/{asset_id}/original", stream=True
        ) as response:
            for chunk in response.iter_content(1024 * 1024):
                count += len(chunk)
                if max_bytes is not None and count > max_bytes:
                    raise ValueError("Server original exceeds expected size")
                digest.update(chunk)
                if destination is not None:
                    destination.write(chunk)
        if max_bytes is not None and count != max_bytes:
            raise ValueError("Server original size differs")
        return digest.hexdigest()

    def copy(self, source_id, target_id, options):
        return self.json(
            "PUT",
            "/assets/copy",
            json={"sourceId": source_id, "targetId": target_id, **options},
        )

    def trash(self, asset_id):
        return self.json("DELETE", "/assets", json={"ids": [asset_id], "force": False})
