from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _norm_key(value: str) -> str:
    """Normalize Vietnamese/property names for loose comparison."""
    value = value.strip().lower()
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return value.replace("_", " ").replace("-", " ")


def _get_prop_loose(pset: dict[str, Any], preferred_name: str) -> Any:
    """Get property by exact name, then by normalized name."""
    if preferred_name in pset:
        return pset.get(preferred_name)
    wanted = _norm_key(preferred_name)
    for key, value in pset.items():
        if _norm_key(str(key)) == wanted:
            return value
    # Common fallbacks for Ma hieu / Mã hiệu
    fallback_keys = ["ma hieu", "mã hiệu", "ma_hieu", "mã_hiệu", "ma cau kien", "mã cấu kiện", "code", "element code"]
    for key, value in pset.items():
        nk = _norm_key(str(key))
        if nk in [_norm_key(k) for k in fallback_keys]:
            return value
    return None


def _get_pset_loose(psets: dict[str, Any], preferred_name: str) -> dict[str, Any] | None:
    if preferred_name in psets and isinstance(psets[preferred_name], dict):
        return psets[preferred_name]
    wanted = _norm_key(preferred_name)
    for key, value in psets.items():
        if _norm_key(str(key)) == wanted and isinstance(value, dict):
            return value
    return None


def extract_elements_from_ifc_file(ifc_path: Path, pset_name: str, code_property: str) -> list[dict[str, str | None]]:
    import ifcopenshell
    from ifcopenshell.util.element import get_psets

    model = ifcopenshell.open(str(ifc_path))
    rows: list[dict[str, str | None]] = []

    for product in model.by_type("IfcProduct"):
        guid = getattr(product, "GlobalId", None)
        if not guid:
            continue

        try:
            psets = get_psets(product) or {}
        except Exception:
            psets = {}

        pset = _get_pset_loose(psets, pset_name)
        if not pset:
            continue

        element_code = _clean_text(_get_prop_loose(pset, code_property))
        if not element_code:
            continue

        element_name = _clean_text(getattr(product, "Name", None))
        rows.append(
            {
                "ifc_file": ifc_path.name,
                "ifc_guid": str(guid),
                "element_code": element_code,
                "element_name": element_name,
                "ifc_class": product.is_a(),
            }
        )

    return rows


def scan_ifc_folder(ifc_folder: Path, pset_name: str, code_property: str) -> tuple[list[dict[str, str | None]], list[str]]:
    ifc_files = sorted(ifc_folder.glob("*.ifc"))
    all_rows: list[dict[str, str | None]] = []
    errors: list[str] = []

    for ifc_path in ifc_files:
        try:
            all_rows.extend(extract_elements_from_ifc_file(ifc_path, pset_name, code_property))
        except Exception as exc:
            errors.append(f"{ifc_path.name}: {exc}")

    return all_rows, errors


def scan_pdf_folder(pdf_folder: Path) -> list[Path]:
    return sorted(pdf_folder.rglob("*.pdf"))


def build_code_mapping(
    ifc_folder: str | Path,
    pdf_folder: str | Path,
    base_url: str,
    pset_name: str = "Thong_tin_BIM",
    code_property: str = "Mã hiệu",
    output_json: str | Path | None = None,
) -> dict[str, Any]:
    ifc_folder = Path(ifc_folder).resolve()
    pdf_folder = Path(pdf_folder).resolve()
    base_url = base_url.rstrip("/")

    if not ifc_folder.exists():
        raise FileNotFoundError(f"IFC folder not found: {ifc_folder}")
    if not pdf_folder.exists():
        raise FileNotFoundError(f"PDF folder not found: {pdf_folder}")

    elements, ifc_errors = scan_ifc_folder(ifc_folder, pset_name, code_property)
    pdfs = scan_pdf_folder(pdf_folder)

    items: dict[str, dict[str, Any]] = {}

    # Group IFC elements by element_code.
    for row in elements:
        code = row["element_code"]
        if not code:
            continue
        item = items.setdefault(
            code,
            {
                "element_code": code,
                "element_name": row.get("element_name"),
                "ifc_guids": [],
                "ifc_files": [],
                "documents": [],
            },
        )
        if row.get("ifc_guid") and row["ifc_guid"] not in item["ifc_guids"]:
            item["ifc_guids"].append(row["ifc_guid"])
        if row.get("ifc_file") and row["ifc_file"] not in item["ifc_files"]:
            item["ifc_files"].append(row["ifc_file"])
        if not item.get("element_name") and row.get("element_name"):
            item["element_name"] = row["element_name"]

    # Match PDFs by exact substring of full element_code in filename.
    for code, item in items.items():
        code_lower = code.lower()
        matched_pdfs = [p for p in pdfs if code_lower in p.name.lower()]
        for index, pdf_path in enumerate(matched_pdfs, start=1):
            rel = pdf_path.relative_to(pdf_folder).as_posix()
            quoted_rel = "/".join(quote(part) for part in rel.split("/"))
            item["documents"].append(
                {
                    "id": f"{code}::{index}",
                    "file_name": pdf_path.name,
                    "file_url": f"{base_url}/{quoted_rel}",
                    "document_type": guess_document_type(pdf_path.name),
                    "revision": None,
                    "status": "active",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "source": "auto_code_mapping",
                }
            )

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ifc_folder": str(ifc_folder),
        "pdf_folder": str(pdf_folder),
        "base_url": base_url,
        "pset_name": pset_name,
        "code_property": code_property,
        "ifc_files_scanned": len(list(ifc_folder.glob("*.ifc"))),
        "ifc_elements_with_code": len(elements),
        "unique_element_codes": len(items),
        "pdf_files_scanned": len(pdfs),
        "matched_codes": sum(1 for item in items.values() if item["documents"]),
        "unmatched_codes": sum(1 for item in items.values() if not item["documents"]),
        "total_document_links": sum(len(item["documents"]) for item in items.values()),
        "ifc_errors": ifc_errors,
        "items": dict(sorted(items.items(), key=lambda kv: kv[0])),
    }

    if output_json:
        output_path = Path(output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return report


def guess_document_type(filename: str) -> str:
    name = filename.lower()
    if "bbnt" in name or "nghiem" in name or "nghiệm" in name:
        return "BBNT"
    if "bvhc" in name or "hoan cong" in name or "hoàn công" in name:
        return "BVHC"
    if "vat lieu" in name or "vật liệu" in name or "cl" in name:
        return "CL"
    return "PDF"


def load_mapping(mapping_json: str | Path) -> dict[str, Any]:
    path = Path(mapping_json)
    if not path.exists():
        return {"items": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def find_by_code(mapping: dict[str, Any], element_code: str) -> dict[str, Any] | None:
    return (mapping.get("items") or {}).get(element_code)


def find_by_guid(mapping: dict[str, Any], ifc_guid: str) -> dict[str, Any] | None:
    for item in (mapping.get("items") or {}).values():
        if ifc_guid in item.get("ifc_guids", []):
            return item
    return None
