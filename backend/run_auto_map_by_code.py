from __future__ import annotations

import argparse
from pathlib import Path

from code_auto_map import build_code_mapping


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto map PDF documents to BIM elements by Mã hiệu / element_code.")
    parser.add_argument("--ifc-folder", default="../data/ifc", help="Folder containing one or more IFC files.")
    parser.add_argument("--pdf-folder", default="../data/pdf", help="Folder containing PDF files.")
    parser.add_argument("--base-url", required=True, help="Public base URL for PDF files, e.g. https://xxx.trycloudflare.com/pdf")
    parser.add_argument("--pset-name", default="Thong_tin_BIM", help="IFC Property Set name.")
    parser.add_argument("--code-property", default="Mã hiệu", help="Property name that stores the element code.")
    parser.add_argument("--output", default="../data/code_mapping.json", help="Output JSON mapping path.")
    args = parser.parse_args()

    report = build_code_mapping(
        ifc_folder=args.ifc_folder,
        pdf_folder=args.pdf_folder,
        base_url=args.base_url,
        pset_name=args.pset_name,
        code_property=args.code_property,
        output_json=args.output,
    )

    print("\n=== AUTO MAPPING BY MÃ HIỆU ===")
    print(f"IFC folder:              {Path(args.ifc_folder).resolve()}")
    print(f"PDF folder:              {Path(args.pdf_folder).resolve()}")
    print(f"Mapping file:            {Path(args.output).resolve()}")
    print(f"IFC files scanned:       {report['ifc_files_scanned']}")
    print(f"Elements with code:      {report['ifc_elements_with_code']}")
    print(f"Unique element codes:    {report['unique_element_codes']}")
    print(f"PDF files scanned:       {report['pdf_files_scanned']}")
    print(f"Matched codes:           {report['matched_codes']}")
    print(f"Unmatched codes:         {report['unmatched_codes']}")
    print(f"Total PDF links:         {report['total_document_links']}")

    if report.get("ifc_errors"):
        print("\nIFC read errors:")
        for err in report["ifc_errors"]:
            print(f"- {err}")

    print("\nDone.")


if __name__ == "__main__":
    main()
