"""Read-only APIs for comparing ADIF snapshots."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.fast_adif_comparison_service import FastADIFComparisonService

router = APIRouter(prefix="/api/comparisons", tags=["comparisons"])


class ADIFSide(BaseModel):
    content: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=100)
    filename: str = Field(default="log.adi", max_length=255)
    coverage: str = "PARTIAL_EXPORT"


class ADIFComparisonRequest(BaseModel):
    a: ADIFSide
    b: ADIFSide


@router.post("/adif", response_model=dict)
def compare_adif(request: ADIFComparisonRequest):
    if request.a.source.strip().upper() == request.b.source.strip().upper():
        raise HTTPException(status_code=400, detail="As duas fontes precisam ter nomes diferentes.")
    try:
        return FastADIFComparisonService().compare(
            content_a=request.a.content,
            content_b=request.b.content,
            source_a=request.a.source.strip().upper(),
            source_b=request.b.source.strip().upper(),
            coverage_a=request.a.coverage,
            coverage_b=request.b.coverage,
            filename_a=request.a.filename,
            filename_b=request.b.filename,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Falha ao comparar ADIFs: {exc}") from exc
