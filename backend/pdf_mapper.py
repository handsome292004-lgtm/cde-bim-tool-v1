from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

from database import add_document, list_elements


def scan_pdf_folder(pdf_folder: str) -> List[Path]:
    folder = Path(pdf_folder)
    if not folder.exists():
        raise FileNotFoundError(f"PDF folder not found: {folder}")
    return sorted([p for p in folder.rglob("*.pdf") if p.is_file()])


def file_to_url(path: Path, *, base_url: Optional[str] = None) -> str:
    """
    Convert a PDF file path to URL.
    If base_url is provided, it creates base_url/file_name.
    Otherwise it stores the local absolute file path as file:// URL for demo only.
    """
    if base_url:
        return base_url.rstrip("/") + "/" + quote(path.name)
    return path.resolve().as_uri()


def auto_map_pdfs(
    *,
    project_id: str,
    model_id: str,
    pdf_folder: str,
    document_type: Optional[str] = None,
    revision: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, object]:
    """
    Match PDFs by full element_code in filename.
    Status:
      MATCHED    = exactly 1 matching PDF
      AMBIGUOUS  = more than 1 matching PDF
      NOT_FOUND  = no matching PDF
    """
    elements = list_elements(project_id=project_id, model_id=model_id)
    pdf_files = scan_pdf_folder(pdf_folder)

    report = []
    matched_count = 0
    ambiguous_count = 0
    not_found_count = 0

    for element in elements:
        code = element.get("element_code")
        if not code:
            report.append({"element": element, "status": "NOT_FOUND", "candidates": []})
            not_found_count += 1
            continue

        candidates = [p for p in pdf_files if code.lower() in p.name.lower()]

        if len(candidates) == 1:
            pdf = candidates[0]
            add_document(
                project_id=project_id,
                model_id=model_id,
                ifc_guid=element["ifc_guid"],
                element_code=element.get("element_code"),
                element_name=element.get("element_name"),
                file_name=pdf.name,
                file_url=file_to_url(pdf, base_url=base_url),
                document_type=document_type,
                revision=revision,
            )
            report.append({"element": element, "status": "MATCHED", "candidates": [str(pdf)]})
            matched_count += 1
        elif len(candidates) > 1:
            report.append({"element": element, "status": "AMBIGUOUS", "candidates": [str(p) for p in candidates]})
            ambiguous_count += 1
        else:
            report.append({"element": element, "status": "NOT_FOUND", "candidates": []})
            not_found_count += 1

    return {
        "summary": {
            "total_elements": len(elements),
            "matched": matched_count,
            "ambiguous": ambiguous_count,
            "not_found": not_found_count,
        },
        "items": report,
    }
