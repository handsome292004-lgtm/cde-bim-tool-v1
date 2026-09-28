from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="CDE BIM PDF Linker API",
    description="Robust backend proxy for scanning PDF files from Trimble Connect project/folders.",
    version="1.4.0-trimble-solid-source",
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
    folder_id: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _normalize_base(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return "https://app.connect.trimble.com/tc/api/2.0"
    return url


def _api_roots(core_api_base: str) -> list[str]:
    """Return /tc/api roots without version, for all likely regions."""
    base = _normalize_base(core_api_base)
    # Strip a terminal /2.0 or /2.1 to get .../tc/api
    root = re.sub(r"/(?:2\.0|2\.1)$", "", base)
    roots = [root]
    for host in [
        "https://app.connect.trimble.com/tc/api",
        "https://app21.connect.trimble.com/tc/api",
        "https://app31.connect.trimble.com/tc/api",
    ]:
        if host not in roots:
            roots.append(host)
    return roots


def _versioned_bases(core_api_base: str) -> list[str]:
    bases: list[str] = []
    for root in _api_roots(core_api_base):
        for ver in ("2.0", "2.1"):
            b = f"{root}/{ver}"
            if b not in bases:
                bases.append(b)
    return bases


def _http_get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, */*",
            "User-Agent": "CDE-BIM-PDF-Linker/1.4",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8", errors="replace")
            if not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:2500]
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def _norm(text: Any) -> str:
    import unicodedata

    text = unicodedata.normalize("NFD", str(text or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return "".join(ch if ch.isalnum() or ch in "_-./ " else "" for ch in text)


def _node_name(node: dict[str, Any]) -> str | None:
    return node.get("name") or node.get("fileName") or node.get("title") or node.get("displayName")


def _node_id(node: dict[str, Any]) -> str | None:
    value = (
        node.get("id")
        or node.get("fileId")
        or node.get("folderId")
        or node.get("identifier")
        or node.get("fileIdentifier")
        or node.get("folderIdentifier")
        or node.get("file_id")
        or node.get("folder_id")
        or node.get("objectId")
        or node.get("versionId")
        or node.get("version_id")
    )
    return str(value) if value is not None else None


def _is_pdf_name(name: Any) -> bool:
    return str(name or "").lower().endswith(".pdf")


def _is_folder_like(node: dict[str, Any]) -> bool:
    kind = str(node.get("type") or node.get("objectType") or node.get("itemType") or node.get("resourceType") or "").lower()
    name = str(_node_name(node) or "")
    if "folder" in kind:
        return True
    if node.get("children") is not None or node.get("items") is not None or node.get("files") is not None or node.get("folders") is not None:
        return True
    # If it has an id/name but no file extension, it may be a folder in some endpoints.
    if _node_id(node) and name and "." not in name and "file" not in kind:
        return True
    return False


def _href(container: dict[str, Any], key: str) -> str | None:
    value = container.get(key)
    if isinstance(value, dict):
        return value.get("href")
    if isinstance(value, str):
        return value
    return None


def _normalize_file(file_obj: dict[str, Any], inherited_path: str = "") -> dict[str, Any]:
    links = file_obj.get("links") if isinstance(file_obj.get("links"), dict) else {}
    links2 = file_obj.get("_links") if isinstance(file_obj.get("_links"), dict) else {}
    file_id = _node_id(file_obj)
    name = _node_name(file_obj)
    path = file_obj.get("path") or file_obj.get("folderPath") or file_obj.get("location") or file_obj.get("parentPath") or inherited_path or ""
    direct_url = (
        file_obj.get("downloadUrl")
        or file_obj.get("url")
        or file_obj.get("webUrl")
        or file_obj.get("viewerUrl")
        or _href(links, "download")
        or _href(links2, "download")
        or _href(links, "self")
        or _href(links2, "self")
        or ""
    )
    return {"id": file_id, "name": name, "path": path, "directUrl": direct_url, "raw": file_obj}


def _collect_files_and_folders(data: Any, inherited_path: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    files: list[dict[str, Any]] = []
    folders: list[dict[str, Any]] = []
    seen: set[int] = set()

    def walk(node: Any, path: str = "") -> None:
        if node is None:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, path)
            return
        if not isinstance(node, dict):
            return
        node_identity = id(node)
        if node_identity in seen:
            return
        seen.add(node_identity)

        name = _node_name(node)
        kind = str(node.get("type") or node.get("objectType") or node.get("itemType") or node.get("resourceType") or "").lower()
        node_path = node.get("path") or node.get("folderPath") or node.get("location") or node.get("parentPath") or path

        if name and (_is_pdf_name(name) or "file" in kind or node.get("fileId") or node.get("fileIdentifier")):
            copied = dict(node)
            copied["name"] = name
            copied["path"] = node_path
            files.append(copied)

        if name and _is_folder_like(node):
            copied = dict(node)
            copied["name"] = name
            copied["path"] = node_path
            folders.append(copied)
            next_path = "/".join([x for x in [path, str(name)] if x])
        else:
            next_path = path

        for value in node.values():
            walk(value, next_path)

    walk(data, inherited_path)
    return files, folders


def _filter_pdfs(items: list[dict[str, Any]], folder_filter: str | None) -> list[dict[str, Any]]:
    ff = _norm(folder_filter)
    output: list[dict[str, Any]] = []
    for item in items:
        normalized = _normalize_file(item)
        name = str(normalized.get("name") or "")
        if not _is_pdf_name(name):
            continue
        if ff:
            searchable = _norm(" / ".join([str(normalized.get("path") or ""), name]))
            if ff not in searchable:
                continue
        output.append(normalized)

    dedup: dict[str, dict[str, Any]] = {}
    for f in output:
        key = f"{f.get('id') or 'noid'}::{f.get('name')}::{f.get('path')}"
        dedup[key] = f
    return sorted(dedup.values(), key=lambda x: str(x.get("name") or ""))


def _project_urls(base: str, project_id: str) -> list[str]:
    p = urllib.parse.quote(project_id, safe="")
    return [
        f"{base}/projects/{p}?fullyLoaded=true",
        f"{base}/projects/{p}",
        f"{base}/projects?fullyLoaded=true&pageSize=1000",
        f"{base}/projects?pageSize=1000",
        f"{base}/projects",
    ]


def _id_values(obj: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for k in ("id", "projectId", "project_id", "identifier", "shortId", "short_id", "uid", "Id", "ID"):
        v = obj.get(k)
        if v is not None:
            values.add(str(v))
    return values


def _extract_project_candidates(data: Any) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    seen: set[int] = set()

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, list):
            for x in node:
                walk(x)
            return
        if not isinstance(node, dict):
            return
        if id(node) in seen:
            return
        seen.add(id(node))
        keys = {str(k).lower() for k in node.keys()}
        if ("id" in keys or "projectid" in keys or "project_id" in keys) and ("name" in keys or "title" in keys):
            projects.append(node)
        for value in node.values():
            walk(value)

    walk(data)
    return projects


def _matches_project(obj: dict[str, Any], project_id: str) -> bool:
    pid = str(project_id or "").strip().lower()
    return pid and pid in {v.lower() for v in _id_values(obj)}


def _extract_folder_ids_from_project(obj: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    candidate_keys = [
        "rootId", "root_id", "rootFolderId", "root_folder_id", "rootFolderIdentifier",
        "folderId", "folder_id", "dataRootFolderId", "data_root_folder_id",
    ]
    for key in candidate_keys:
        value = obj.get(key)
        if value and str(value) not in ids:
            ids.append(str(value))
    for key in ("rootFolder", "root", "folder"):
        value = obj.get(key)
        if isinstance(value, dict):
            fid = _node_id(value)
            if fid and fid not in ids:
                ids.append(fid)
    return ids


def _folder_by_path_urls(base: str, project_id: str, path: str) -> list[str]:
    p = urllib.parse.quote(project_id, safe="")
    # Try both with and without leading slash; some APIs are strict.
    raw_paths = []
    cleaned = (path or "").strip().strip("/")
    for x in (cleaned, f"/{cleaned}" if cleaned else "/"):
        if x not in raw_paths:
            raw_paths.append(x)
    urls = []
    for rp in raw_paths:
        q = urllib.parse.urlencode({"projectId": project_id, "path": rp})
        q2 = urllib.parse.urlencode({"project_id": project_id, "path": rp})
        urls.extend([f"{base}/folders/by_path?{q}", f"{base}/folders/by_path?{q2}"])
    return urls


def _folder_items_urls(base: str, folder_id: str, project_id: str | None = None) -> list[str]:
    fid = urllib.parse.quote(str(folder_id), safe="")
    urls = [
        f"{base}/folders/{fid}/items?pageSize=1000",
        f"{base}/folders/{fid}/items",
        f"{base}/folders/{fid}/children?pageSize=1000",
        f"{base}/folders/{fid}/children",
        f"{base}/folders/{fid}?fullyLoaded=true",
        f"{base}/folders/{fid}",
    ]
    if project_id:
        p = urllib.parse.quote(project_id, safe="")
        urls.extend([
            f"{base}/projects/{p}/folders/{fid}/items?pageSize=1000",
            f"{base}/projects/{p}/folders/{fid}/items",
            f"{base}/projects/{p}/folders/{fid}?fullyLoaded=true",
            f"{base}/projects/{p}/folders/{fid}",
        ])
    return urls


def _direct_file_urls(base: str, project_id: str) -> list[str]:
    p = urllib.parse.quote(project_id, safe="")
    return [
        f"{base}/files?projectId={p}&pageSize=1000",
        f"{base}/files?project_id={p}&pageSize=1000",
        f"{base}/projects/{p}/files?fullyLoaded=true&pageSize=1000",
        f"{base}/projects/{p}/files?pageSize=1000",
        f"{base}/projects/{p}/files",
        f"{base}/projects/{p}/documents?fullyLoaded=true&pageSize=1000",
        f"{base}/projects/{p}/documents?pageSize=1000",
        f"{base}/projects/{p}/folders?includeFiles=true&pageSize=1000",
    ]


def _scan_response(files: list[dict[str, Any]], project_id: str, source_url: str, source_mode: str, errors: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "ok": True,
        "project_id": project_id,
        "count": len(files),
        "files": files,
        "source_url": source_url,
        "source_mode": source_mode,
        "errors_before_success": errors[-20:],
    }


def _try_json_url(url: str, token: str, errors: list[dict[str, str]]) -> Any | None:
    try:
        return _http_get_json(url, token)
    except Exception as exc:  # noqa: BLE001
        errors.append({"url": url, "error": str(exc)})
        print(f"ERROR {url}: {exc}", flush=True)
        return None


def _scan_folder_recursive(base: str, folder_id: str, token: str, project_id: str, folder_filter: str | None, errors: list[dict[str, str]], depth: int = 0, max_depth: int = 8, seen_folders: set[str] | None = None) -> tuple[list[dict[str, Any]], str | None]:
    seen_folders = seen_folders or set()
    if not folder_id or folder_id in seen_folders or depth > max_depth:
        return [], None
    seen_folders.add(folder_id)
    collected_file_objs: list[dict[str, Any]] = []

    for url in _folder_items_urls(base, folder_id, project_id):
        print(f"Trying folder items URL: {url}", flush=True)
        data = _try_json_url(url, token, errors)
        if data is None:
            continue
        files, folders = _collect_files_and_folders(data)
        print(f"Folder response: raw files={len(files)}, folders={len(folders)}", flush=True)
        collected_file_objs.extend(files)
        # recurse into child folders
        for folder in folders:
            child_id = _node_id(folder)
            if not child_id:
                continue
            child_files, _ = _scan_folder_recursive(base, child_id, token, project_id, folder_filter, errors, depth + 1, max_depth, seen_folders)
            # child_files already normalized; mark with sentinel raw type to avoid normalize twice? Easier append raw back not possible.
            collected_file_objs.extend([f.get("raw", f) for f in child_files])
        pdfs = _filter_pdfs(collected_file_objs, folder_filter)
        if pdfs:
            return pdfs, url
        # If endpoint read OK but no PDFs, don't keep trying aliases for same folder too long.
        errors.append({"url": url, "error": f"Folder read OK; files={len(files)}, folders={len(folders)}, pdfs=0"})
    return [], None


@app.post("/api/trimble/scan-pdfs")
def scan_trimble_pdfs(payload: TrimbleScanRequest) -> dict[str, Any]:
    core = _normalize_base(payload.core_api_base)
    project_id = payload.project_id.strip()
    folder_filter = payload.folder_filter or ""
    manual_folder_id = (payload.folder_id or "").strip()
    errors: list[dict[str, str]] = []

    print("\n================ TRIMBLE PDF SCAN DEBUG V1.4 ================", flush=True)
    print(f"Project ID   : {project_id}", flush=True)
    print(f"Input API    : {core}", flush=True)
    print(f"Folder filter: {folder_filter}", flush=True)
    print(f"Manual folder: {manual_folder_id}", flush=True)

    if not core.startswith("https://"):
        return {"ok": False, "message": "core_api_base phải bắt đầu bằng https://", "files": [], "candidate_errors": []}

    bases = _versioned_bases(core)
    print(f"Candidate bases: {bases}", flush=True)

    # 1) Manual folder ID is the most reliable because Trimble files are organized by folder IDs.
    if manual_folder_id:
        for base in bases:
            files, source = _scan_folder_recursive(base, manual_folder_id, payload.token, project_id, folder_filter, errors)
            if files:
                print("SUCCESS by manual folder ID.", flush=True)
                return _scan_response(files, project_id, source or "manual_folder", "manual_folder_id_recursive", errors)

    # 2) Try folder path lookup for requested folder name/path, then root path.
    path_candidates = []
    if folder_filter.strip():
        path_candidates.append(folder_filter.strip())
    path_candidates.extend(["/", ""])
    for base in bases:
        for path in path_candidates:
            for url in _folder_by_path_urls(base, project_id, path):
                print(f"Trying folder by path URL: {url}", flush=True)
                data = _try_json_url(url, payload.token, errors)
                if data is None:
                    continue
                files0, folders0 = _collect_files_and_folders(data)
                pdfs0 = _filter_pdfs(files0, folder_filter)
                if pdfs0:
                    print("SUCCESS by folder by_path payload.", flush=True)
                    return _scan_response(pdfs0, project_id, url, "folder_by_path_payload", errors)
                folder_ids = []
                # data itself can be a folder object, or can contain folders
                if isinstance(data, dict):
                    fid = _node_id(data)
                    if fid:
                        folder_ids.append(fid)
                for folder in folders0:
                    fid = _node_id(folder)
                    if fid and fid not in folder_ids:
                        folder_ids.append(fid)
                print(f"Folder by path response: files={len(files0)}, folders={len(folders0)}, folder_ids={folder_ids[:5]}", flush=True)
                for fid in folder_ids[:10]:
                    files, source = _scan_folder_recursive(base, fid, payload.token, project_id, folder_filter, errors)
                    if files:
                        print("SUCCESS by folder by_path then recursive items.", flush=True)
                        return _scan_response(files, project_id, source or url, "folder_by_path_recursive", errors)

    # 3) Try project detail/list to discover root folder id or fully-loaded files.
    for base in bases:
        for url in _project_urls(base, project_id):
            print(f"Trying project URL: {url}", flush=True)
            data = _try_json_url(url, payload.token, errors)
            if data is None:
                continue
            file_objs, folder_objs = _collect_files_and_folders(data)
            pdfs = _filter_pdfs(file_objs, folder_filter)
            print(f"Project response: file_objs={len(file_objs)}, folder_objs={len(folder_objs)}, pdfs={len(pdfs)}", flush=True)
            if pdfs:
                print("SUCCESS by project payload files.", flush=True)
                return _scan_response(pdfs, project_id, url, "project_payload", errors)

            candidate_projects = []
            if isinstance(data, dict) and _matches_project(data, project_id):
                candidate_projects.append(data)
            candidate_projects.extend([p for p in _extract_project_candidates(data) if _matches_project(p, project_id)])
            # If there is a single visible project in a list, it is often the current one.
            if not candidate_projects:
                projects = _extract_project_candidates(data)
                if len(projects) == 1:
                    candidate_projects = projects
            folder_ids: list[str] = []
            for proj in candidate_projects:
                for fid in _extract_folder_ids_from_project(proj):
                    if fid not in folder_ids:
                        folder_ids.append(fid)
            # Also try folder ids discovered in the project payload.
            for folder in folder_objs:
                fid = _node_id(folder)
                if fid and fid not in folder_ids:
                    folder_ids.append(fid)
            print(f"Project response candidate folder IDs: {folder_ids[:10]}", flush=True)
            for fid in folder_ids[:25]:
                files, source = _scan_folder_recursive(base, fid, payload.token, project_id, folder_filter, errors)
                if files:
                    print("SUCCESS by project-discovered folder recursion.", flush=True)
                    return _scan_response(files, project_id, source or url, "project_folder_recursive", errors)

    # 4) Last resort: direct-looking file endpoints.
    for base in bases:
        for url in _direct_file_urls(base, project_id):
            print(f"Trying direct file URL: {url}", flush=True)
            data = _try_json_url(url, payload.token, errors)
            if data is None:
                continue
            files0, _ = _collect_files_and_folders(data)
            pdfs = _filter_pdfs(files0, folder_filter)
            print(f"Direct response: file_objs={len(files0)}, pdfs={len(pdfs)}", flush=True)
            if pdfs:
                print("SUCCESS by direct file endpoint.", flush=True)
                return _scan_response(pdfs, project_id, url, "direct_file_endpoint", errors)
            errors.append({"url": url, "error": f"Direct endpoint read OK; file_objs={len(files0)}, pdfs=0"})

    message = (
        "Chưa quét được PDF từ Trimble API. Backend đã thử nhiều region, /folders/by_path, "
        "/folders/{id}/items, /projects và các endpoint files/documents. "
        "Cách chắc chắn tiếp theo: mở đúng thư mục PDF trong Trimble Explorer, copy Folder ID trên URL, "
        "dán vào ô 'Folder ID tùy chọn', rồi quét lại."
    )
    detail = {
        "ok": False,
        "message": message,
        "project_id": project_id,
        "input_core_api_base": core,
        "tried_bases": bases,
        "folder_filter": folder_filter,
        "folder_id": manual_folder_id,
        "files": [],
        "candidate_errors": errors[-80:],
    }
    print("SCAN FAILED DETAIL:", json.dumps(detail, ensure_ascii=False, indent=2)[:12000], flush=True)
    print("==============================================================\n", flush=True)
    return detail
