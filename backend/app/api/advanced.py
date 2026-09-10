"""Advanced analysis endpoints: multi-source ADIF comparison and QSL evidence."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.advanced_analysis_service import AdvancedAnalysisService

router = APIRouter(prefix="/api/advanced", tags=["advanced-analysis"])


class AdvancedADIFSource(BaseModel):
    content: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=100)
    filename: str = Field(default="log.adi", max_length=255)
    coverage: str = "PARTIAL_EXPORT"
    kind: Optional[str] = Field(default=None, max_length=30)
    assume_received: bool = True


class MultiComparisonRequest(BaseModel):
    sources: List[AdvancedADIFSource] = Field(min_length=2, max_length=12)
    reference_index: int = 0


class QSLAnalysisRequest(BaseModel):
    reference: AdvancedADIFSource
    evidence_sources: List[AdvancedADIFSource] = Field(min_length=1, max_length=12)


@router.post("/compare", response_model=dict)
def compare_many(request: MultiComparisonRequest):
    try:
        return AdvancedAnalysisService().compare_sources(
            sources=[item.model_dump() for item in request.sources],
            reference_index=request.reference_index,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Falha na comparação avançada: {exc}") from exc


@router.post("/qsl", response_model=dict)
def analyze_qsl(request: QSLAnalysisRequest):
    try:
        return AdvancedAnalysisService().analyze_qsl(
            reference=request.reference.model_dump(),
            evidence_sources=[item.model_dump() for item in request.evidence_sources],
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Falha na análise de QSLs: {exc}") from exc
