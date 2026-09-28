from typing import List, Optional
from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    project_id: str = Field(..., min_length=1)
    model_id: str = Field(..., min_length=1)
    ifc_guid: str = Field(..., min_length=1)
    element_code: Optional[str] = None
    element_name: Optional[str] = None
    file_name: Optional[str] = None
    file_url: str = Field(..., min_length=1)
    document_type: Optional[str] = None
    revision: Optional[str] = None


class DocumentOut(BaseModel):
    id: int
    file_name: Optional[str] = None
    file_url: str
    document_type: Optional[str] = None
    revision: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DocsResponse(BaseModel):
    project_id: str
    model_id: str
    ifc_guid: str
    element_code: Optional[str] = None
    element_name: Optional[str] = None
    documents: List[DocumentOut] = []


class ElementCreate(BaseModel):
    project_id: str = Field(..., min_length=1)
    model_id: str = Field(..., min_length=1)
    ifc_guid: str = Field(..., min_length=1)
    element_code: Optional[str] = None
    element_name: Optional[str] = None


class ImportIfcRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    model_id: str = Field(..., min_length=1)
    ifc_path: str = Field(..., min_length=1)
    pset_name: str = "Thong_tin_BIM"
    code_property: str = "Mã hiệu"


class AutoMapRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    model_id: str = Field(..., min_length=1)
    pdf_folder: str = Field(..., min_length=1)
    document_type: Optional[str] = None
    revision: Optional[str] = None
    base_url: Optional[str] = None
