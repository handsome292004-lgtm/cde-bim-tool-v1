from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="CDE BIM PDF Linker API",
    description="Backend proxy for CDE BIM PDF Linker. It helps the Trimble extension scan project PDFs without browser CORS issues.",
    version="1.2.0-trimble-pdf-proxy",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TrimbleScanRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    token: str = Field(..., min_length=10)
    core_api_base: str = "https://app.connect.trimble.com/tc/api/2.0"
    folder_filter: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _normalize_base(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _http_get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, */*",
            "User-Agent": "CDE-BIM-PDF-Linker/1.2",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            if not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def _collect_file_like_objects(data: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[int] = set()

    def walk(node: Any, inherited_path: str = "") -> None:
        if node is None:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, inherited_path)
            return
        if not isinstance(node, dict):
            return

        node_id = id(node)
        if node_id in seen:
            return
        seen.add(node_id)

        name = node.get("name") or node.get("fileName") or node.get("title") or node.get("displayName")
        kind = str(node.get("type") or node.get("objectType") or node.get("itemType") or "").lower()
        path = node.get("path") or node.get("folderPath") or node.get("location") or inherited_path

        if name and ("file" in kind or "." in str(name)):
            copied = dict(node)
            copied["name"] = name
            copied["path"] = path
            output.append(copied)

        is_folder = bool(name) and ("folder" in kind or "children" in node or "items" in node)
        next_path = "/".join([x for x in [inherited_path, str(name) if is_folder else ""] if x])
        for value in node.values():
            walk(value, next_path or inherited_path)

    walk(data)
    return output


def _norm(text: Any) -> str:
    import unicodedata
    text = unicodedata.normalize("NFD", str(text or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return "".join(ch if ch.isalnum() or ch in "_-./ " else "" for ch in text)


def _normalize_file(file_obj: dict[str, Any]) -> dict[str, Any]:
    links = file_obj.get("links") if isinstance(file_obj.get("links"), dict) else {}
    links2 = file_obj.get("_links") if isinstance(file_obj.get("_links"), dict) else {}

    def href(container: dict[str, Any], key: str) -> str | None:
        value = container.get(key)
        if isinstance(value, dict):
            return value.get("href")
        if isinstance(value, str):
            return value
        return None

    file_id = (
        file_obj.get("id")
        or file_obj.get("fileId")
        or file_obj.get("identifier")
        or file_obj.get("fileIdentifier")
        or file_obj.get("file_id")
        or file_obj.get("objectId")
        or file_obj.get("versionId")
        or file_obj.get("version_id")
    )
    name = file_obj.get("name") or file_obj.get("fileName") or file_obj.get("title") or file_obj.get("displayName")
    path = file_obj.get("path") or file_obj.get("folderPath") or file_obj.get("location") or file_obj.get("parentPath") or ""
    direct_url = (
        file_obj.get("downloadUrl")
        or file_obj.get("url")
        or file_obj.get("webUrl")
        or file_obj.get("viewerUrl")
        or href(links, "download")
        or href(links2, "download")
        or href(links, "self")
        or href(links2, "self")
        or ""
    )
    return {"id": file_id, "name": name, "path": path, "directUrl": direct_url, "raw": file_obj}


def _candidate_urls(base: str, project_id: str) -> list[str]:
    p = urllib.parse.quote(project_id, safe="")
    return [
        f"{base}/projects/{p}/files?fullyLoaded=true&pageSize=1000",
        f"{base}/projects/{p}/files?includeFolders=true&pageSize=1000",
        f"{base}/projects/{p}/files?pageSize=1000",
        f"{base}/projects/{p}/files",
        f"{base}/projects/{p}/documents?fullyLoaded=true&pageSize=1000",
        f"{base}/projects/{p}/documents?pageSize=1000",
        f"{base}/projects/{p}/documents",
        f"{base}/projects/{p}/folders?includeFiles=true&pageSize=1000",
    ]


@app.post("/api/trimble/scan-pdfs")
def scan_trimble_pdfs(payload: TrimbleScanRequest) -> dict[str, Any]:
    base = _normalize_base(payload.core_api_base)
    if not base.startswith("https://"):
        raise HTTPException(status_code=400, detail="core_api_base phải bắt đầu bằng https://")

    folder_filter = _norm(payload.folder_filter)
    errors: list[dict[str, str]] = []

    for url in _candidate_urls(base, payload.project_id):
        try:
            data = _http_get_json(url, payload.token)
            items = _collect_file_like_objects(data)
            files = []
            for item in items:
                normalized = _normalize_file(item)
                name = str(normalized.get("name") or "")
                if not name.lower().endswith(".pdf"):
                    continue
                if folder_filter:
                    searchable = _norm(" / ".join([str(normalized.get("path") or ""), name]))
                    if folder_filter not in searchable:
                        continue
                files.append(normalized)

            if files:
                # de-duplicate by id/name/path
                dedup: dict[str, dict[str, Any]] = {}
                for f in files:
                    key = f"{f.get('id') or 'noid'}::{f.get('name')}::{f.get('path')}"
                    dedup[key] = f
                return {
                    "project_id": payload.project_id,
                    "count": len(dedup),
                    "files": sorted(dedup.values(), key=lambda x: str(x.get("name") or "")),
                    "source_url": url,
                    "errors_before_success": errors,
                }

            errors.append({"url": url, "error": f"API đọc được nhưng không tìm thấy PDF. Items={len(items)}"})
        except Exception as exc:  # noqa: BLE001
            errors.append({"url": url, "error": str(exc)})

    raise HTTPException(
        status_code=502,
        detail={
            "message": "Không quét được PDF từ Trimble Core API. Có thể sai API base/region, token thiếu quyền file, hoặc endpoint file của project khác mẫu hiện tại.",
            "project_id": payload.project_id,
            "core_api_base": base,
            "folder_filter": payload.folder_filter,
            "candidate_errors": errors,
        },
    )
