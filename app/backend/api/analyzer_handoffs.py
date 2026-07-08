from fastapi import APIRouter

from app.backend.models.analyzer_handoff_import import (
    AnalyzerHandoffImportRequest,
    AnalyzerHandoffImportResult,
)
from app.backend.services.analyzer_handoff_import_service import (
    AnalyzerHandoffImportService,
)


router = APIRouter()
analyzer_handoff_import_service = AnalyzerHandoffImportService()


@router.post("/import", response_model=AnalyzerHandoffImportResult)
def import_analyzer_handoff(
    request: AnalyzerHandoffImportRequest,
) -> AnalyzerHandoffImportResult:
    return analyzer_handoff_import_service.import_output(request.output_dir)
