from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from database import add_document, delete_document, init_db, list_documents, upsert_element, list_elements
from schemas import AutoMapRequest, DocumentCreate, ElementCreate, ImportIfcRequest

app = FastAPI(
    title="CDE BIM PDF Linker API",
    description="FastAPI backend for linking PDF documents to IFC objects selected in Trimble Connect.",
    version="1.0.0",
)

# During development, keep CORS open so GitHub Pages / local HTML can call the API.
# For production, replace allow_origins=["*"] with your real extension domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/docs")
def get_docs(
    project_id: str = Query(..., min_length=1),
    model_id: str = Query(..., min_length=1),
    ifc_guid: str = Query(..., min_length=1),
) -> dict:
    """Return all documents attached to a selected IFC object."""
    return list_documents(project_id=project_id, model_id=model_id, ifc_guid=ifc_guid)


@app.post("/api/docs", status_code=201)
def create_doc(payload: DocumentCreate) -> dict:
    """Attach one PDF/document URL to one BIM element."""
    created = add_document(
        project_id=payload.project_id,
        model_id=payload.model_id,
        ifc_guid=payload.ifc_guid,
        element_code=payload.element_code,
        element_name=payload.element_name,
        file_name=payload.file_name,
        file_url=payload.file_url,
        document_type=payload.document_type,
        revision=payload.revision,
    )
    return {"message": "document_created", "document": created}


@app.delete("/api/docs/{document_id}")
def remove_doc(document_id: int) -> dict:
    ok = delete_document(document_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"message": "document_deleted", "id": document_id}


@app.post("/api/elements", status_code=201)
def create_or_update_element(payload: ElementCreate) -> dict:
    element = upsert_element(
        project_id=payload.project_id,
        model_id=payload.model_id,
        ifc_guid=payload.ifc_guid,
        element_code=payload.element_code,
        element_name=payload.element_name,
    )
    return {"message": "element_saved", "element": element}


@app.get("/api/elements")
def get_elements(project_id: str | None = None, model_id: str | None = None) -> dict:
    return {"items": list_elements(project_id=project_id, model_id=model_id)}


@app.post("/api/import-ifc")
def import_ifc(payload: ImportIfcRequest) -> dict:
    """
    Optional V1+ endpoint: read IFC by IfcOpenShell and save elements into SQLite.
    This endpoint expects the IFC path to exist on the backend machine.
    """
    from ifc_reader import extract_elements_from_ifc

    path = Path(payload.ifc_path)
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"IFC file not found: {payload.ifc_path}")

    try:
        items = extract_elements_from_ifc(
            str(path),
            pset_name=payload.pset_name,
            code_property=payload.code_property,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    saved = []
    for item in items:
        saved.append(
            upsert_element(
                project_id=payload.project_id,
                model_id=payload.model_id,
                ifc_guid=item["ifc_guid"],
                element_code=item.get("element_code"),
                element_name=item.get("element_name"),
            )
        )

    return {"message": "ifc_imported", "count": len(saved), "items": saved}


@app.post("/api/auto-map")
def auto_map(payload: AutoMapRequest) -> dict:
    """
    Optional V1+ endpoint: match PDFs by full element_code in filename.
    Use only after /api/import-ifc has already saved elements.
    """
    from pdf_mapper import auto_map_pdfs

    try:
        return auto_map_pdfs(
            project_id=payload.project_id,
            model_id=payload.model_id,
            pdf_folder=payload.pdf_folder,
            document_type=payload.document_type,
            revision=payload.revision,
            base_url=payload.base_url,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
