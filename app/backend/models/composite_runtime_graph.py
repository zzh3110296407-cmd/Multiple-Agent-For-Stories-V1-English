from typing import Any, Literal

from pydantic import BaseModel, Field, root_validator, validator


PHASE85C_M7_RUNTIME_GRAPH_VERSION = "phase85c_m7_composite_runtime_graph_v1"
SCENE_GENERATION_CANDIDATE_GRAPH_ID = "scene_generation_candidate_graph_v1"

CompositeRuntimeGraphMode = Literal["candidate_preview", "commit_boundary_preview"]

COMPOSITE_RUNTIME_GRAPH_STATUSES = {
    "initialized",
    "input_validated",
    "scene_participation_ready",
    "memory_context_ready",
    "character_intent_ready",
    "story_information_ready",
    "writer_candidate_ready",
    "gate_reviewed",
    "candidate_output_ready",
    "waiting_user_confirmation",
    "commit_boundary_verified",
    "writeback_plan_ready",
    "completed_candidate_graph",
    "blocked",
    "failed",
}

COMPOSITE_RUNTIME_GRAPH_NODE_ORDER = [
    "N0 InputNormalizer",
    "N1 SceneAgent",
    "N2 MemoryCuratorAgent.run_for_scene_context",
    "N3 CharacterPsychologyActionIntentAgent",
    "N4 ABCDStoryInformationIntegratorNode",
    "N5 WriterAgent",
    "N6 PostDraftGateReceiptValidator",
    "N7 CandidateSceneOutputAssembler",
    "N8 UserConfirmationCommitBoundaryPreview",
    "N9 MemoryCuratorAgent.plan_writeback_after_commit",
    "N10 GraphAuthorityAudit",
]

COMPOSITE_RUNTIME_REQUIRED_EDGES = [
    ("N0 InputNormalizer", "N1 SceneAgent"),
    ("N1 SceneAgent", "N2 MemoryCuratorAgent.run_for_scene_context"),
    ("N1 SceneAgent", "N3 CharacterPsychologyActionIntentAgent"),
    ("N3 CharacterPsychologyActionIntentAgent", "N4 ABCDStoryInformationIntegratorNode"),
    ("N4 ABCDStoryInformationIntegratorNode", "N5 WriterAgent"),
    ("N5 WriterAgent", "N6 PostDraftGateReceiptValidator"),
    ("N6 PostDraftGateReceiptValidator", "N7 CandidateSceneOutputAssembler"),
    ("N7 CandidateSceneOutputAssembler", "N8 UserConfirmationCommitBoundaryPreview"),
    ("N8 UserConfirmationCommitBoundaryPreview", "N9 MemoryCuratorAgent.plan_writeback_after_commit"),
]


class CompositeRuntimeGraphInputRefs(BaseModel):
    chapter_plan_id: str = ""
    scene_role_function_need_ids: list[str] = Field(default_factory=list)
    existing_scene_participation_package_id: str = ""
    existing_abcd_story_information_package_id: str = ""
    mock_user_confirmation_receipt_id: str = ""

    @validator("scene_role_function_need_ids", pre=True)
    def list_refs_must_be_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class CompositeRuntimeNode(BaseModel):
    node_id: str
    node_name: str
    order_index: int
    agent_name: str = ""
    target_scope: str = ""
    required: bool = True
    safe_summary: str = ""


class CompositeRuntimeEdge(BaseModel):
    from_node_id: str
    to_node_id: str
    rule: str
    required: bool = True


class CompositeRuntimeGraphDefinition(BaseModel):
    graph_id: str = SCENE_GENERATION_CANDIDATE_GRAPH_ID
    version_id: str = PHASE85C_M7_RUNTIME_GRAPH_VERSION
    default_mode: CompositeRuntimeGraphMode = "candidate_preview"
    nodes: list[CompositeRuntimeNode] = Field(default_factory=list)
    edges: list[CompositeRuntimeEdge] = Field(default_factory=list)
    candidate_only: bool = True
    live_commit_supported: bool = False
    live_writeback_supported: bool = False
    safe_summary: str = ""

    @validator("graph_id")
    def graph_id_must_match_v1(cls, value: str) -> str:
        if value != SCENE_GENERATION_CANDIDATE_GRAPH_ID:
            raise ValueError("Unsupported composite runtime graph id")
        return value

    @validator("candidate_only", always=True)
    def candidate_only_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M7 graph definition must remain candidate-only")
        return True

    @validator("live_commit_supported", "live_writeback_supported", always=True)
    def live_modes_must_be_false(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("M7 does not support live commit or live writeback")
        return False


class CompositeRuntimeGraphRunRequest(BaseModel):
    graph_run_id: str = ""
    graph_id: str = SCENE_GENERATION_CANDIDATE_GRAPH_ID
    project_id: str
    chapter_id: str
    scene_id: str
    scene_index: int
    scene_goal: str = ""
    scene_location: str = ""
    mode: CompositeRuntimeGraphMode = "candidate_preview"
    input_refs: CompositeRuntimeGraphInputRefs = Field(
        default_factory=CompositeRuntimeGraphInputRefs
    )
    dry_run: bool = True
    force_refresh: bool = False
    created_at: str = ""

    @validator("graph_id")
    def graph_id_must_match_v1(cls, value: str) -> str:
        if value != SCENE_GENERATION_CANDIDATE_GRAPH_ID:
            raise ValueError("Unsupported composite runtime graph id")
        return value

    @validator("scene_index")
    def scene_index_must_be_positive(cls, value: int) -> int:
        if int(value or 0) < 1:
            raise ValueError("scene_index must be >= 1")
        return value

    @validator("dry_run", always=True)
    def dry_run_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M7 graph requests must be dry_run=true")
        return True

    @validator("project_id", "chapter_id", "scene_id")
    def ids_must_be_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("M7 graph request ids must be non-empty")
        return text


class CompositeRuntimeNodeReceipt(BaseModel):
    node_receipt_id: str
    graph_run_id: str
    node_id: str
    order_index: int
    status: str
    agent_name: str = ""
    wrapper_run_id: str = ""
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    gate_receipt_ids: list[str] = Field(default_factory=list)
    story_fact_delta_empty: bool = True
    candidate_only: bool = True
    can_write_story_facts_directly: bool = False
    blocking_findings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str = ""

    @validator(
        "input_refs",
        "output_refs",
        "gate_receipt_ids",
        "blocking_findings",
        "warnings",
        pre=True,
    )
    def list_fields_must_be_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("candidate_only", always=True)
    def node_receipts_are_candidate_only(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M7 node receipts must remain candidate-only")
        return True

    @validator("can_write_story_facts_directly", always=True)
    def node_receipts_cannot_write_facts(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("M7 node receipts cannot grant story fact writes")
        return False


class CandidateSceneOutput(BaseModel):
    candidate_scene_output_id: str
    writer_candidate_draft_id: str
    graph_run_id: str
    project_id: str
    chapter_id: str
    scene_id: str
    scene_index: int
    candidate_synopsis: str = ""
    candidate_prose: str = ""
    source_scene_prose_plan_id: str = ""
    source_psychology_visibility_plan_id: str = ""
    source_beat_sheet_id: str = ""
    source_prose_draft_package_id: str = ""
    source_reader_experience_report_id: str = ""
    source_psychology_overexposure_report_id: str = ""
    source_prose_style_inspection_report_id: str = ""
    source_hook_payoff_inspection_report_id: str = ""
    source_subtext_balance_inspection_report_id: str = ""
    source_writer_self_revision_report_id: str = ""
    writer_self_revision_applied: bool = False
    writer_quality_issue_codes: list[str] = Field(default_factory=list)
    gate_receipt_ids: list[str] = Field(default_factory=list)
    source_node_receipt_ids: list[str] = Field(default_factory=list)
    eligible_for_user_confirmation: bool = True
    eligible_for_commit_service_review: bool = True
    candidate_only: bool = True
    can_write_scene_directly: bool = False
    can_write_story_facts_directly: bool = False
    story_fact_delta_empty: bool = True
    safe_summary: str = ""

    @validator("gate_receipt_ids", "source_node_receipt_ids", "writer_quality_issue_codes", pre=True)
    def list_fields_must_be_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("candidate_only", "story_fact_delta_empty", always=True)
    def true_flags_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M7 candidate scene output must remain candidate-only")
        return True

    @validator("can_write_scene_directly", "can_write_story_facts_directly", always=True)
    def write_flags_must_be_false(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("M7 candidate scene output cannot write directly")
        return False


class CommitBoundaryPreviewReceipt(BaseModel):
    commit_boundary_receipt_id: str
    graph_run_id: str
    source_candidate_scene_output_id: str
    source_user_confirmation_receipt_id: str
    preview_only: bool = True
    does_not_commit_scene: bool = True
    does_not_write_story_facts: bool = True
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""

    @validator("warnings", pre=True)
    def warnings_must_be_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator(
        "preview_only",
        "does_not_commit_scene",
        "does_not_write_story_facts",
        always=True,
    )
    def boundary_flags_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M7 commit boundary is preview-only")
        return True


class WritebackPlanPreviewRef(BaseModel):
    writeback_plan_ref_id: str
    graph_run_id: str
    source_commit_boundary_receipt_id: str
    memory_curator_run_id: str
    plan_refs: list[str] = Field(default_factory=list)
    writeback_plan_only: bool = True
    dry_run: bool = True
    active_memory_write_executed: bool = False
    safe_summary: str = ""
    warnings: list[str] = Field(default_factory=list)

    @validator("plan_refs", "warnings", pre=True)
    def list_fields_must_be_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))

    @validator("writeback_plan_only", "dry_run", always=True)
    def true_flags_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("M7 writeback preview must be plan-only dry-run")
        return True

    @validator("active_memory_write_executed", always=True)
    def active_write_must_be_false(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("M7 writeback preview cannot execute active memory writes")
        return False


class CompositeRuntimeGraphSequenceReport(BaseModel):
    graph_run_id: str
    sequence_valid: bool
    node_order: list[str] = Field(default_factory=list)
    expected_order: list[str] = Field(default_factory=lambda: list(COMPOSITE_RUNTIME_GRAPH_NODE_ORDER))
    required_edges: list[dict[str, str]] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    safe_summary: str = ""

    @validator("node_order", "expected_order", "violations", pre=True)
    def list_fields_must_be_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class CompositeRuntimeGraphAuthorityAudit(BaseModel):
    graph_run_id: str
    authority_audit_passed: bool
    candidate_gate_commit_writeback_order_preserved: bool
    story_fact_delta_empty: bool
    no_write_audit_passed: bool = True
    all_node_story_fact_delta_empty: bool
    no_node_claims_committed_authority: bool
    candidate_output_candidate_only: bool
    no_frontend_or_api_mutation: bool = True
    checked_node_receipt_ids: list[str] = Field(default_factory=list)
    blocking_findings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_summary: str = ""

    @validator("checked_node_receipt_ids", "blocking_findings", "warnings", pre=True)
    def list_fields_must_be_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class CompositeRuntimeGraphTrace(BaseModel):
    graph_trace_id: str
    graph_run_id: str
    graph_id: str
    mode: CompositeRuntimeGraphMode
    node_receipt_ids: list[str] = Field(default_factory=list)
    agent_run_ids: list[str] = Field(default_factory=list)
    gate_receipt_ids: list[str] = Field(default_factory=list)
    candidate_scene_output_ref: str = ""
    commit_boundary_receipt_ref: str = ""
    writeback_plan_ref: str = ""
    safe_summary: str = ""
    created_at: str = ""

    @validator("node_receipt_ids", "agent_run_ids", "gate_receipt_ids", pre=True)
    def list_fields_must_be_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class CompositeRuntimeGraphEvidenceIndex(BaseModel):
    graph_id: str
    graph_run_id: str
    mode: CompositeRuntimeGraphMode
    status: str
    report_files: list[str] = Field(default_factory=list)
    prerequisite_markers: list[str] = Field(default_factory=list)
    final_marker: str
    generated_at: str = ""

    @validator("report_files", "prerequisite_markers", pre=True)
    def list_fields_must_be_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


class CompositeRuntimeGraphRunResult(BaseModel):
    graph_id: str
    graph_run_id: str
    mode: CompositeRuntimeGraphMode
    status: str
    final_decision: str
    node_receipts: list[CompositeRuntimeNodeReceipt] = Field(default_factory=list)
    node_order: list[str] = Field(default_factory=list)
    agent_run_ids: list[str] = Field(default_factory=list)
    gate_receipt_ids: list[str] = Field(default_factory=list)
    candidate_scene_output: CandidateSceneOutput | None = None
    commit_boundary_preview_receipt: CommitBoundaryPreviewReceipt | None = None
    writeback_plan_preview_ref: WritebackPlanPreviewRef | None = None
    sequence_report: CompositeRuntimeGraphSequenceReport
    authority_audit: CompositeRuntimeGraphAuthorityAudit
    trace: CompositeRuntimeGraphTrace
    warnings: list[str] = Field(default_factory=list)
    blocking_findings: list[str] = Field(default_factory=list)
    safe_summary: str = ""
    final_marker: str = ""
    generated_at: str = ""

    @root_validator(skip_on_failure=True)
    def status_must_be_known(cls, values: dict[str, Any]) -> dict[str, Any]:
        status = str(values.get("status") or "")
        if status not in COMPOSITE_RUNTIME_GRAPH_STATUSES:
            raise ValueError(f"Unknown M7 graph status: {status}")
        return values

    @validator(
        "node_order",
        "agent_run_ids",
        "gate_receipt_ids",
        "warnings",
        "blocking_findings",
        pre=True,
    )
    def list_fields_must_be_strings(cls, value: Any) -> list[str]:
        return _unique_strings(_as_list(value))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple) or isinstance(value, set):
        return list(value)
    return [value]


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
