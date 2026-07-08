from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.abcd_runtime_gate import (
    ABCDApparentContradictionLink,
    ABCDContinuityRuntimeIssue,
)
from app.backend.models.apparent_contradiction import ApparentContradictionGateResult
from app.backend.models.continuity import ContinuityIssue
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.apparent_contradiction_gate_service import (
    ApparentContradictionGateService,
)
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.storage.json_store import JsonStore


class ABCDApparentContradictionBridge:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        apparent_gate_service: ApparentContradictionGateService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.apparent_gate_service = apparent_gate_service or ApparentContradictionGateService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )

    def evaluate(
        self,
        *,
        bundle: dict[str, Any],
        runtime_issues: list[ABCDContinuityRuntimeIssue],
        continuity_issues: list[ContinuityIssue],
        mode: str,
    ) -> tuple[list[ABCDApparentContradictionLink], ApparentContradictionGateResult]:
        context = bundle["context"]
        scene = bundle["scene"]
        continuity_context = {
            "scene": scene,
            "scene_id": scene.scene_id,
            "chapter_id": scene.chapter_id,
            "target_type": "scene",
            "target_id": scene.scene_id,
            "generation_trace_id": scene.generation_trace.generation_trace_id,
            "target_text_excerpt": context.safe_context_summary,
            "source_memory_ids": [
                memory_id
                for ids in context.source_memory_ids_by_character.values()
                for memory_id in ids
            ],
        }
        result = self.apparent_gate_service.evaluate_issues(
            continuity_context=continuity_context,
            issues=continuity_issues,
            mode=mode,
        )
        issue_by_continuity_id = {
            issue.continuity_issue_id: issue
            for issue in runtime_issues
        }
        classifications = {
            item.issue_id: item
            for item in result.classifications
        }
        records = {
            item.source_issue_id: item
            for item in result.apparent_records
        }
        timestamp = utc_now()
        links: list[ABCDApparentContradictionLink] = []
        for continuity_issue in result.gated_issues:
            runtime_issue = issue_by_continuity_id.get(continuity_issue.issue_id)
            if runtime_issue is None:
                continue
            classification = classifications.get(continuity_issue.issue_id)
            record = records.get(continuity_issue.issue_id)
            links.append(
                ABCDApparentContradictionLink(
                    link_id=f"abcd_apparent_link_{runtime_issue.runtime_issue_id}",
                    project_id=context.project_id,
                    scene_id=context.scene_id,
                    source_issue_id=runtime_issue.runtime_issue_id,
                    source_character_id=runtime_issue.character_id,
                    source_artifact_type=runtime_issue.source_artifact_type,
                    source_artifact_id=runtime_issue.source_artifact_id,
                    apparent_contradiction_id=(
                        record.apparent_contradiction_id if record else ""
                    ),
                    narrative_debt_id=(
                        classification.matched_narrative_debt_ids[0]
                        if classification and classification.matched_narrative_debt_ids
                        else ""
                    ),
                    matched_claim_ids=(
                        classification.matched_claim_ids if classification else []
                    ),
                    matched_perception_state_ids=(
                        classification.matched_perception_state_ids
                        if classification
                        else []
                    ),
                    matched_psychology_trace_ids=(
                        classification.matched_psychology_trace_ids
                        if classification
                        else []
                    ),
                    matched_expression_record_ids=(
                        classification.matched_expression_record_ids
                        if classification
                        else []
                    ),
                    matched_narrative_intent_ids=(
                        classification.matched_narrative_intent_ids
                        if classification
                        else []
                    ),
                    apparent_gate_action=continuity_issue.apparent_gate_action
                    or (classification.quality_gate_action if classification else ""),
                    safe_summary=(
                        classification.safe_user_summary
                        if classification
                        else runtime_issue.safe_summary
                    ),
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        return links, result
