"""Local ADIF comparison and QSL review APIs; no remote writes."""
from __future__ import annotations

import io
import json
import zipfile
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..services.adif_workbench import ADIFWorkbench, csv_report

router = APIRouter(prefix='/api/adif-workbench', tags=['adif-qsl'])


class SourceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal['LOG', 'EQSL_RECEIVED', 'LOTW', 'PAPER'] = 'LOG'
    coverage: Literal['FULL_EXPORT', 'PARTIAL_EXPORT'] = 'PARTIAL_EXPORT'
    content: str = Field(min_length=1, max_length=100_000_000)
    filename: str = Field(default='log.adi', max_length=255)


class ComparisonRequest(BaseModel):
    base_id: str
    source_ids: list[str] = Field(min_length=1, max_length=50)


class QSLRequest(BaseModel):
    target_id: str
    source_ids: list[str] = Field(min_length=1, max_length=50)
    tolerance: int = Field(default=300, ge=0, le=300)


class QSLExport(QSLRequest):
    revision: str
    selected: list[str] = Field(min_length=1)


def run(fn):
    try:
        return fn()
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def download(text, filename, media='text/csv'):
    return Response(text.encode('utf-8'), media_type=media, headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@router.get('/sources')
def sources():
    return run(lambda: ADIFWorkbench().sources())


@router.post('/sources')
def create_source(request: SourceRequest):
    return run(lambda: ADIFWorkbench().save(**request.model_dump()))


@router.put('/sources/{source_id}')
def update_source(source_id: str, request: SourceRequest):
    return run(lambda: ADIFWorkbench().save(**request.model_dump(), source_id=source_id))


@router.delete('/sources/{source_id}')
def delete_source(source_id: str):
    return run(lambda: ADIFWorkbench().delete(source_id))


@router.get('/sources/{source_id}/original')
def original_source(source_id: str):
    source = run(lambda: ADIFWorkbench().load(source_id))
    return download(source['content'], 'original.adi', 'text/plain')


@router.post('/compare')
def compare(request: ComparisonRequest):
    return run(lambda: ADIFWorkbench().compare(**request.model_dump()))


@router.post('/compare/export')
def export_comparison(request: ComparisonRequest):
    result = run(lambda: ADIFWorkbench().compare(**request.model_dump()))
    return download(csv_report(result['findings']), 'comparacao-adif.csv')


@router.post('/qsl')
def qsl(request: QSLRequest):
    return run(lambda: ADIFWorkbench().qsl(**request.model_dump()))


@router.post('/qsl/report')
def qsl_report(request: QSLRequest):
    result = run(lambda: ADIFWorkbench().qsl(**request.model_dump()))
    return download(csv_report(result['proposals'] + result['unmatched']), 'validacao-qsl.csv')


@router.post('/qsl/export')
def qsl_export(request: QSLExport):
    corrected, original, proposals = run(lambda: ADIFWorkbench().export_qsl(**request.model_dump()))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('log-original.adi', original)
        archive.writestr('log-com-confirmacoes.adi', corrected)
        archive.writestr('alteracoes.csv', csv_report(proposals))
        archive.writestr('evidencias.json', json.dumps(proposals, ensure_ascii=False, indent=2))
        archive.writestr('LEIA-ME.txt', 'QSO Manager 7.0 — proposta local de confirmações\n\n'
            'log-original.adi: base usada na análise (snapshot normalizado quando a origem é online).\n'
            'log-com-confirmacoes.adi: log completo com somente as propostas selecionadas aplicadas.\n'
            'alteracoes.csv e evidencias.json: valores anteriores, alterações e evidências.\n'
            'Nenhuma alteração foi enviada a QRZ, eQSL, LoTW ou outro serviço.\n'
            'Revise as alterações antes de importar o arquivo no seu programa de log.\n'
            'Reimportar no QRZ não garante atualização de campos; use o relatório para ajuste manual quando necessário.\n')
    return Response(stream.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="qsl-revisado.zip"'})
