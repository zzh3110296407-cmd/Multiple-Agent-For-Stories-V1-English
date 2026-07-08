from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.backend.models.product_artifacts import DebugIsolationAudit, DebugVisibilityPolicy
from app.backend.services.debug_isolation_audit_service import DebugIsolationAuditService
from app.backend.services.debug_visibility_service import DebugVisibilityService
from app.backend.storage.json_store import StorageError


router = APIRouter()
debug_visibility_service = DebugVisibilityService()
debug_isolation_audit_service = DebugIsolationAuditService()


@router.get("/policy", response_model=DebugVisibilityPolicy)
def get_debug_visibility_policy() -> DebugVisibilityPolicy:
    return debug_visibility_service.policy()


@router.get("/audit", response_model=DebugIsolationAudit)
def get_debug_visibility_audit(
    project_id: Optional[str] = Query(default=None),
) -> DebugIsolationAudit:
    try:
        return debug_isolation_audit_service.audit(project_id=project_id)
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
