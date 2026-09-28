from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


def _normalize_key(text: str) -> str:
    return text.strip().lower().replace("_", " ")


def extract_elements_from_ifc(
    ifc_path: str,
    *,
    pset_name: str = "Thong_tin_BIM",
    code_property: str = "Mã hiệu",
) -> List[Dict[str, Optional[str]]]:
    """
    Read an IFC file and return objects with IFC GlobalId and the business element code.

    This function requires ifcopenshell:
        pip install ifcopenshell
    """
    try:
        import ifcopenshell
        import ifcopenshell.util.element
    except Exception as exc:  # pragma: no cover - depends on local environment
        raise RuntimeError(
            "IfcOpenShell is not installed or cannot be imported. Run: pip install ifcopenshell"
        ) from exc

    path = Path(ifc_path)
    if not path.exists():
        raise FileNotFoundError(f"IFC file not found: {path}")

    model = ifcopenshell.open(str(path))
    results: list[dict[str, Any]] = []
    target_pset = _normalize_key(pset_name)
    target_prop = _normalize_key(code_property)

    # Broad set of common physical IFC products. You can narrow this later.
    for obj in model.by_type("IfcProduct"):
        guid = getattr(obj, "GlobalId", None)
        if not guid:
            continue

        element_code = None
        element_name = getattr(obj, "Name", None)

        psets = ifcopenshell.util.element.get_psets(obj) or {}
        for pset_key, props in psets.items():
            if _normalize_key(pset_key) != target_pset:
                continue
            for prop_key, prop_value in props.items():
                if _normalize_key(prop_key) == target_prop:
                    element_code = str(prop_value) if prop_value is not None else None
                    break

        # Keep only objects that have the BIM business code.
        if element_code:
            results.append(
                {
                    "ifc_guid": guid,
                    "element_code": element_code,
                    "element_name": element_name,
                }
            )

    return results
