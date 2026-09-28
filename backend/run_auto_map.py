from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import quote

from database import add_document, init_db, list_documents, upsert_element
from ifc_reader import extract_elements_from_ifc


def normalize(text: str | None) -> str:
    return (text or "").strip().lower()


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-map PDF files to IFC elements by element_code.")
    parser.add_argument("--project-id", required=True, help="Trimble project id shown in the extension panel")
    parser.add_argument("--model-id", required=True, help="Trimble model id shown after selecting an object")
    parser.add_argument("--ifc", required=True, help="Path to IFC file, e.g. ../data/ifc/model.ifc")
    parser.add_argument("--pdf-folder", default="../data/pdf", help="Folder containing PDF files")
    parser.add_argument("--base-url", required=True, help="Public backend URL for PDFs, e.g. https://xxx.trycloudflare.com/pdf")
    parser.add_argument("--pset-name", default="Thong_tin_BIM", help="IFC Property Set name containing element code")
    parser.add_argument("--code-property", default="Mã hiệu", help="Property name containing element code")
    parser.add_argument("--document-type", default="PDF", help="Document type saved to database")
    parser.add_argument("--revision", default=None, help="Optional revision, e.g. R01")
    args = parser.parse_args()

    init_db()

    ifc_path = Path(args.ifc).resolve()
    pdf_folder = Path(args.pdf_folder).resolve()

    if not ifc_path.exists():
        raise SystemExit(f"IFC file not found: {ifc_path}")
    if not pdf_folder.exists():
        raise SystemExit(f"PDF folder not found: {pdf_folder}")

    print(f"Reading IFC: {ifc_path}")
    elements = extract_elements_from_ifc(
        str(ifc_path),
        pset_name=args.pset_name,
        code_property=args.code_property,
    )
    print(f"Found {len(elements)} IFC elements")

    pdf_files = sorted(pdf_folder.rglob("*.pdf"))
    print(f"Found {len(pdf_files)} PDF files")

    total_matched = 0
    total_created = 0
    total_skipped_duplicate = 0
    no_code = 0
    no_match = 0

    for item in elements:
        ifc_guid = item.get("ifc_guid")
        element_code = item.get("element_code")
        element_name = item.get("element_name")

        if not ifc_guid:
            continue

        upsert_element(
            project_id=args.project_id,
            model_id=args.model_id,
            ifc_guid=ifc_guid,
            element_code=element_code,
            element_name=element_name,
        )

        if not element_code:
            no_code += 1
            continue

        code_norm = normalize(element_code)
        matches = [p for p in pdf_files if code_norm in normalize(p.name)]

        if not matches:
            no_match += 1
            continue

        existing = list_documents(
            project_id=args.project_id,
            model_id=args.model_id,
            ifc_guid=ifc_guid,
        )
        existing_urls = {d.get("file_url") for d in existing.get("documents", [])}

        print(f"\n{element_code}: {len(matches)} PDF matched")
        for pdf in matches:
            rel = pdf.relative_to(pdf_folder).as_posix()
            file_url = f"{args.base_url.rstrip('/')}/{quote(rel, safe='/')}"
            total_matched += 1

            if file_url in existing_urls:
                total_skipped_duplicate += 1
                print(f"  SKIP duplicate: {pdf.name}")
                continue

            add_document(
                project_id=args.project_id,
                model_id=args.model_id,
                ifc_guid=ifc_guid,
                element_code=element_code,
                element_name=element_name,
                file_name=pdf.name,
                file_url=file_url,
                document_type=args.document_type,
                revision=args.revision,
            )
            total_created += 1
            print(f"  ADD: {pdf.name}")

    print("\n=== AUTO MAP REPORT ===")
    print(f"Elements in IFC:             {len(elements)}")
    print(f"PDF files scanned:           {len(pdf_files)}")
    print(f"PDF matches found:           {total_matched}")
    print(f"New document records created:{total_created}")
    print(f"Duplicate records skipped:   {total_skipped_duplicate}")
    print(f"Elements without code:       {no_code}")
    print(f"Elements with no PDF match:  {no_match}")


if __name__ == "__main__":
    main()
