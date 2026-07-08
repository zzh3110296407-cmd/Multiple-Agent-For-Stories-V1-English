from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.project_creation import ProjectOriginMetadata
from app.backend.models.project_story_premise import (
    PROJECT_STORY_PREMISE_SCHEMA_VERSION,
    ProjectStoryPremise,
    ProjectStoryPremiseReadiness,
    ProjectStoryPremiseResponse,
    PromptFidelityContract,
    PromptSourceRef,
)
from app.backend.models.story_setup import StorySetupHandoff, StorySetupPrompt, StorySetupUserInput
from app.backend.services.active_project_story_data import story_data_dir_for_project
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.services.project_creation_service import ProjectCreationService
from app.backend.services.prompt_anchor_classification_service import classify_prompt_anchor_values
from app.backend.storage.json_store import JsonStore, StorageError


PROJECT_STORY_PREMISE_FILE = "project_story_premise.json"
STORY_SETUP_USER_INPUTS_FILE = "story_setup_user_inputs.json"

PROJECT_STORY_PREMISE_MISSING = "project_story_premise_missing"
PROJECT_STORY_PREMISE_MISSING_CONTROLLED_PROMPT = "project_story_premise_missing_controlled_prompt"
PROJECT_STORY_PREMISE_DEMO_DEFAULT_LEAK = "project_story_premise_demo_default_leak"
PROJECT_STORY_PREMISE_PROJECT_MISMATCH = "project_story_premise_project_mismatch"
PROJECT_STORY_PREMISE_SECRET_LIKE_TEXT_BLOCKED = "project_story_premise_secret_like_text_blocked"

CANONICAL_DEMO_DEFAULT_PREMISE = "我想写一个小城中的异常规则正在改变人们记忆的悬疑故事"
FORBIDDEN_DEMO_DEFAULTS = [
    CANONICAL_DEMO_DEFAULT_PREMISE,
    f"{CANONICAL_DEMO_DEFAULT_PREMISE}。",
    "æˆ‘æƒ³å†™ä¸€ä¸ªå°åŸŽä¸­çš„å¼‚å¸¸è§„åˆ™æ­£åœ¨æ”¹å˜äººä»¬è®°å¿†çš„æ‚¬ç–‘æ•…äº‹",
]

SECRET_LIKE_RE = re.compile(
    r"(?<![A-Za-z])sk-[A-Za-z0-9_\-]{8,}|lsv2_[A-Za-z0-9_\-]{8,}|(?i:bearer\s+[A-Za-z0-9._\-]{8,})|(?i:authorization\s*:)"
)
UNSAFE_VALUE_MARKERS = (
    "raw_prompt",
    "raw response",
    "raw_response",
    "hidden_reasoning",
    "hidden reasoning",
    "internal_reasoning",
    "internal reasoning",
    "chain-of-thought",
    "chain of thought",
    "chain_of_thought",
    "provider_payload",
    "provider payload",
    "provider_response",
    "provider response",
    "api_key",
    "api_key_ref",
)
MARKER_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){2,}\b")
CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")
ALNUM_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_\-]{2,}\b")
LIST_SPLIT_RE = re.compile(r"[、,，;；/]|(?:\s+and\s+)")
PROMPT_STORY_ANCHOR_META_MARKERS = (
    "用户提供",
    "用户输入",
    "提示词",
    "原典提示",
    "文言原文",
    "原文中出现",
    "明确指涉",
    "创作一部",
    "长篇中文故事",
    "故事人物",
    "只能来自",
    "只能来源",
    "不得",
    "现代校园",
    "现代侦探",
    "模板",
    "非原文",
    "每章",
    "每幕",
    "要求",
    "角色可自主",
    "自主行动",
    "心理推进",
    "冲突转折",
    "主角自述",
    "主角奔走",
    "主角在现实",
)
PROMPT_STORY_ANCHOR_GENERIC_CJK = {
    "人物",
    "角色",
    "故事",
    "神灵",
    "君主",
    "历史人物",
    "媒介者",
    "象征性人格",
    "媒介者与象征性人格",
}


class ProjectStoryPremiseError(RuntimeError):
    """Base error for project story premise failures."""


class ProjectStoryPremiseNotFound(ProjectStoryPremiseError):
    """Raised when the current project has no premise."""


class ProjectStoryPremiseBlocked(ProjectStoryPremiseError):
    """Raised when a required premise contract is blocked."""


class ProjectStoryPremiseSafetyError(ProjectStoryPremiseError):
    """Raised when controlled text is unsafe for premise persistence."""


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if isinstance(model, BaseModel):
        return model.dict()
    return dict(model)


class ProjectStoryPremiseService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        project_creation_service: ProjectCreationService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.project_creation_service = project_creation_service or ProjectCreationService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.user_inputs_file = self.data_dir / STORY_SETUP_USER_INPUTS_FILE

    def build_from_story_setup(
        self,
        *,
        prompt: StorySetupPrompt,
        handoff: StorySetupHandoff,
        story_data_dir: Path | None = None,
    ) -> ProjectStoryPremise:
        if prompt.project_id != handoff.project_id:
            raise ProjectStoryPremiseBlocked(PROJECT_STORY_PREMISE_PROJECT_MISMATCH)
        controlled_text = self._controlled_prompt_text(prompt.controlled_prompt_text_ref)
        if not controlled_text:
            raise ProjectStoryPremiseBlocked(PROJECT_STORY_PREMISE_MISSING_CONTROLLED_PROMPT)
        self._guard_controlled_text(controlled_text)

        origin = self.project_creation_service.get_project_origin(prompt.project_id)
        if origin.project_id != prompt.project_id or not origin.is_prompt_first:
            raise ProjectStoryPremiseBlocked(PROJECT_STORY_PREMISE_PROJECT_MISMATCH)

        now = utc_now()
        marker_counts = self.marker_counts(controlled_text)
        demo_count = self.demo_default_count(controlled_text)
        prompt_markers_detected = [marker for marker, count in marker_counts.items() if count > 0]
        blocking_issues = []
        if demo_count > 0:
            blocking_issues.append(PROJECT_STORY_PREMISE_DEMO_DEFAULT_LEAK)
        terms = self.extract_terms(controlled_text)
        prompt_anchor_classification = classify_prompt_anchor_values([controlled_text], limit=64)
        premise = ProjectStoryPremise(
            project_id=prompt.project_id,
            origin_type="prompt_first",
            source_status="controlled_prompt",
            source_refs=PromptSourceRef(
                project_origin_metadata_id=prompt.project_origin_metadata_id,
                project_creation_request_id=prompt.creation_request_id or "",
                source_prompt_ref=prompt.prompt_text_ref or origin.source_prompt_ref or "",
                story_setup_prompt_id=prompt.story_setup_prompt_id,
                controlled_prompt_text_ref=prompt.controlled_prompt_text_ref or "",
                story_setup_handoff_id=handoff.story_setup_handoff_id,
            ),
            user_story_premise=self._bounded_controlled_text(controlled_text),
            safe_user_story_summary=self._safe_summary(controlled_text),
            core_terms=terms["core_terms"],
            setting_terms=terms["setting_terms"],
            conflict_terms=terms["conflict_terms"],
            role_terms=terms["role_terms"],
            required_story_elements=terms["required_story_elements"],
            prompt_markers_detected=prompt_markers_detected,
            forbidden_demo_defaults=list(FORBIDDEN_DEMO_DEFAULTS),
            demo_default_leak_detected=demo_count > 0,
            prompt_fidelity_contract=PromptFidelityContract(
                required_markers=prompt_markers_detected,
                forbidden_markers=prompt_anchor_classification.forbidden_anchors,
                meta_markers=prompt_anchor_classification.meta_control_terms,
                marker_counts=marker_counts,
                forbidden_demo_defaults=list(FORBIDDEN_DEMO_DEFAULTS),
                demo_default_count=demo_count,
                required_terms_present={term: term in controlled_text for term in terms["required_story_elements"]},
            ),
            blocking_issues=blocking_issues,
            warnings=[],
            created_at=now,
            updated_at=now,
        )
        self._guard_safe_payload(model_to_dict(premise))
        self.write_for_project(prompt.project_id, premise, story_data_dir=story_data_dir)
        return premise

    def write_for_project(
        self,
        project_id: str,
        premise: ProjectStoryPremise,
        *,
        story_data_dir: Path | None = None,
    ) -> None:
        if premise.project_id != project_id:
            raise ProjectStoryPremiseBlocked(PROJECT_STORY_PREMISE_PROJECT_MISMATCH)
        target_dir = story_data_dir or story_data_dir_for_project(project_id, self.data_dir)
        self.store.write(target_dir / PROJECT_STORY_PREMISE_FILE, model_to_dict(premise))

    def read_for_project(self, project_id: str) -> ProjectStoryPremise | None:
        path = story_data_dir_for_project(project_id, self.data_dir) / PROJECT_STORY_PREMISE_FILE
        if not self.store.exists(path):
            return None
        try:
            premise = ProjectStoryPremise(**self.store.read(path))
        except (StorageError, ValidationError, TypeError) as exc:
            raise StorageError(f"Storage file is invalid: {PROJECT_STORY_PREMISE_FILE}") from exc
        if premise.project_id != project_id:
            raise ProjectStoryPremiseBlocked(PROJECT_STORY_PREMISE_PROJECT_MISMATCH)
        return premise

    def read_from_story_data_dir(
        self,
        project_id: str,
        story_data_dir: Path,
    ) -> ProjectStoryPremise | None:
        path = story_data_dir / PROJECT_STORY_PREMISE_FILE
        if not self.store.exists(path):
            return None
        try:
            premise = ProjectStoryPremise(**self.store.read(path))
        except (StorageError, ValidationError, TypeError) as exc:
            raise StorageError(f"Storage file is invalid: {PROJECT_STORY_PREMISE_FILE}") from exc
        if premise.project_id != project_id:
            raise ProjectStoryPremiseBlocked(PROJECT_STORY_PREMISE_PROJECT_MISMATCH)
        return premise

    def require_for_project(self, project_id: str) -> ProjectStoryPremise:
        premise = self.read_for_project(project_id)
        if not premise:
            raise ProjectStoryPremiseNotFound(PROJECT_STORY_PREMISE_MISSING)
        if premise.blocking_issues:
            raise ProjectStoryPremiseBlocked(",".join(premise.blocking_issues))
        return premise

    def require_from_story_data_dir(
        self,
        project_id: str,
        story_data_dir: Path,
    ) -> ProjectStoryPremise:
        premise = self.read_from_story_data_dir(project_id, story_data_dir)
        if not premise:
            raise ProjectStoryPremiseNotFound(PROJECT_STORY_PREMISE_MISSING)
        if premise.blocking_issues:
            raise ProjectStoryPremiseBlocked(",".join(premise.blocking_issues))
        return premise

    def require_for_current_active_project(self) -> ProjectStoryPremise:
        project_id = self._active_project_id()
        if not project_id:
            raise ProjectStoryPremiseNotFound(PROJECT_STORY_PREMISE_MISSING)
        return self.require_for_project(project_id)

    def get_current_response(self) -> ProjectStoryPremiseResponse:
        project_id = self._active_project_id()
        if not project_id:
            readiness = ProjectStoryPremiseReadiness(
                readiness_status="missing",
                source_status="missing",
                blocking_issues=[PROJECT_STORY_PREMISE_MISSING],
                safe_summary="No active project is selected.",
            )
            return ProjectStoryPremiseResponse(active_project_id="", readiness=readiness, premise=None, safe_summary=readiness.safe_summary)
        premise = self.read_for_project(project_id)
        if not premise:
            readiness = ProjectStoryPremiseReadiness(
                project_id=project_id,
                readiness_status="missing",
                source_status="missing",
                blocking_issues=[PROJECT_STORY_PREMISE_MISSING],
                safe_summary="Active project has no controlled story premise yet.",
            )
            return ProjectStoryPremiseResponse(active_project_id=project_id, readiness=readiness, premise=None, safe_summary=readiness.safe_summary)
        readiness_status = "ready" if not premise.blocking_issues else "blocked"
        readiness = ProjectStoryPremiseReadiness(
            project_id=project_id,
            readiness_status=readiness_status,
            source_status=premise.source_status,
            blocking_issues=list(premise.blocking_issues),
            warnings=list(premise.warnings),
            safe_summary=f"Project story premise is {readiness_status}.",
        )
        return ProjectStoryPremiseResponse(
            active_project_id=project_id,
            readiness=readiness,
            premise=premise,
            safe_summary=readiness.safe_summary,
            source_refs=model_to_dict(premise.source_refs),
        )

    def coverage_for_payload(self, project_id: str, payload: Any) -> dict[str, Any]:
        premise = self.require_for_project(project_id)
        text = self._payload_text(payload)
        return {
            "marker_counts": self.marker_counts(text),
            "demo_default_count": self.demo_default_count(text),
            "contains_required_terms": self.contains_required_terms(project_id, text),
            "source_status": premise.source_status,
            "blocking_issues": list(premise.blocking_issues),
        }

    def contains_required_terms(self, project_id: str, payload: Any) -> dict[str, bool]:
        premise = self.require_for_project(project_id)
        text = self._payload_text(payload)
        return {term: term in text for term in premise.required_story_elements}

    def marker_counts(self, payload: Any) -> dict[str, int]:
        text = self._payload_text(payload)
        markers = sorted(set(MARKER_RE.findall(text)))
        return {marker: text.count(marker) for marker in markers}

    def demo_default_count(self, payload: Any) -> int:
        text = self._payload_text(payload)
        return sum(text.count(default) for default in FORBIDDEN_DEMO_DEFAULTS)

    def extract_terms(self, text: str) -> dict[str, list[str]]:
        classification = classify_prompt_anchor_values([text], limit=96)
        markers = MARKER_RE.findall(text)
        cjk_terms = CJK_RE.findall(text)
        entity_terms = self._entity_list_terms(text)
        alnum_terms = [
            term
            for term in ALNUM_RE.findall(text)
            if not term.startswith("PHASE85_") and term.lower() not in {"the", "and", "with", "must", "include"}
        ]
        classified_keys = {self._term_key(term) for term in classification.positive_required_anchors}
        forbidden_keys = {self._term_key(term) for term in classification.forbidden_anchors}
        meta_keys = {self._term_key(term) for term in classification.meta_control_terms}
        ordered = [
            term
            for term in self._unique([*classification.positive_required_anchors, *markers, *cjk_terms, *alnum_terms])
            if self._is_story_anchor_term(term) and self._term_key(term) in classified_keys
        ]
        setting = self._classified_terms(ordered, ("世界", "城市", "小城", "地点", "setting", "world", "space", "canvas"))
        conflict = self._classified_terms(ordered, ("冲突", "矛盾", "危机", "异常", "conflict", "pressure", "mystery"))
        role = self._unique(
            [
                *[
                    term
                    for term in entity_terms
                    if self._is_story_anchor_term(term)
                    and self._term_key(term) not in forbidden_keys
                    and self._term_key(term) not in meta_keys
                ],
                *self._classified_terms(
                    ordered,
                    ("角色", "主角", "人物", "神灵", "君主", "历史人物", "媒介者", "role", "character", "function"),
                ),
            ]
        )
        core = self._unique([*markers, *ordered[:12]])
        required = self._unique([*markers, *setting[:4], *conflict[:4], *role[:8], *ordered[:6]])
        return {
            "core_terms": core[:24],
            "setting_terms": setting[:16],
            "conflict_terms": conflict[:16],
            "role_terms": role,
            "required_story_elements": required[:32],
        }

    def _controlled_prompt_text(self, controlled_ref: str | None) -> str:
        if not controlled_ref:
            return ""
        user_input_id = controlled_ref.removeprefix("story_setup_user_input:")
        for record in self._read_user_inputs():
            if record.story_setup_user_input_id == user_input_id and record.input_type == "controlled_prompt_text":
                return record.input_text
        return ""

    def _read_user_inputs(self) -> list[StorySetupUserInput]:
        if not self.store.exists(self.user_inputs_file):
            return []
        try:
            return [StorySetupUserInput(**item) for item in self.store.read_list(self.user_inputs_file)]
        except (StorageError, ValidationError, TypeError) as exc:
            raise StorageError(f"Storage file is invalid: {STORY_SETUP_USER_INPUTS_FILE}") from exc

    def _active_project_id(self) -> str:
        selection = self.project_creation_service.get_active_project_selection().active_project_selection
        return selection.project_id if selection else ""

    def _safe_summary(self, text: str) -> str:
        clean = " ".join((text or "").split())
        return clean[:240]

    def _bounded_controlled_text(self, text: str) -> str:
        clean = " ".join((text or "").split())
        if len(clean) > 8000:
            raise ProjectStoryPremiseSafetyError("project_story_premise_controlled_prompt_too_long")
        return clean

    def _guard_controlled_text(self, text: str) -> None:
        if not (text or "").strip():
            raise ProjectStoryPremiseBlocked(PROJECT_STORY_PREMISE_MISSING_CONTROLLED_PROMPT)
        if SECRET_LIKE_RE.search(text or ""):
            raise ProjectStoryPremiseSafetyError(PROJECT_STORY_PREMISE_SECRET_LIKE_TEXT_BLOCKED)
        lowered = (text or "").lower()
        for marker in UNSAFE_VALUE_MARKERS:
            if marker in lowered:
                raise ProjectStoryPremiseSafetyError(f"project_story_premise_unsafe_marker:{marker}")

    def _guard_safe_payload(self, payload: Any) -> None:
        text = self._payload_text(payload).lower()
        for marker in UNSAFE_VALUE_MARKERS:
            if marker in text:
                raise ProjectStoryPremiseSafetyError(f"project_story_premise_unsafe_marker:{marker}")
        if SECRET_LIKE_RE.search(self._payload_text(payload)):
            raise ProjectStoryPremiseSafetyError(PROJECT_STORY_PREMISE_SECRET_LIKE_TEXT_BLOCKED)

    def _payload_text(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _classified_terms(self, terms: list[str], hints: tuple[str, ...]) -> list[str]:
        lowered_hints = tuple(hint.lower() for hint in hints)
        return [
            term
            for term in terms
            if any(hint in term.lower() or hint in term for hint in lowered_hints)
        ]

    def _is_story_anchor_term(self, value: str) -> bool:
        clean = " ".join(str(value or "").split()).strip()
        if not clean:
            return False
        if clean in PROMPT_STORY_ANCHOR_GENERIC_CJK:
            return False
        if clean.startswith("-") or clean.startswith("要求"):
            return False
        if any(marker in clean for marker in PROMPT_STORY_ANCHOR_META_MARKERS):
            return False
        if len(clean) > 18 and not MARKER_RE.fullmatch(clean):
            return False
        return True

    def _entity_list_terms(self, text: str) -> list[str]:
        terms: list[str] = []
        pending_role_list = False
        for segment in re.split(r"[\n。.!?！？]", str(text or "")):
            if not self._looks_like_role_list_segment(segment) and not pending_role_list:
                pending_role_list = self._looks_like_role_list_intro(segment)
                continue
            list_text = segment
            if "：" in list_text:
                list_text = list_text.split("：", 1)[1]
            elif ":" in list_text:
                list_text = list_text.split(":", 1)[1]
            added_from_segment = False
            for raw in LIST_SPLIT_RE.split(list_text):
                clean = self._clean_entity_term(raw)
                if self._is_entity_like_term(clean):
                    terms.append(clean)
                    added_from_segment = True
            pending_role_list = (
                not added_from_segment and self._looks_like_role_list_intro(segment)
            )
        return self._unique(terms)

    def _looks_like_role_list_intro(self, segment: str) -> bool:
        clean = str(segment or "")
        if "：" not in clean and ":" not in clean:
            return False
        return self._has_role_list_hint(clean)

    def _looks_like_role_list_segment(self, segment: str) -> bool:
        clean = str(segment or "")
        if "、" not in clean and "，" not in clean and "," not in clean:
            return False
        return self._has_role_list_hint(clean)

    def _has_role_list_hint(self, clean: str) -> bool:
        lowered = clean.casefold()
        if any(
            hint in lowered
            for hint in (
                "characters",
                "character list",
                "roles",
                "role list",
                "cast",
                "participants",
            )
        ):
            return True
        return any(
            hint in clean
            for hint in (
                "人物",
                "角色",
                "神灵",
                "君主",
                "历史人物",
                "媒介者",
                "象征性人格",
                "只能来自",
                "只能来源",
            )
        )

    def _clean_entity_term(self, value: str) -> str:
        clean = " ".join(str(value or "").split()).strip()
        clean = clean.strip(" \t\r\n：:，,。.;；、\"'“”‘’（）()[]【】")
        while clean.endswith("等") and len(clean) > 2:
            clean = clean[:-1].strip()
        return clean

    def _is_entity_like_term(self, value: str) -> bool:
        clean = str(value or "").strip()
        if len(clean) > 16:
            return False
        if len(clean) < 2 and not self._is_single_cjk_entity(clean):
            return False
        if any(
            marker in clean
            for marker in (
                "故事",
                "只能",
                "来自",
                "来源",
                "原文",
                "核心",
                "模板",
                "非原文",
                "人物作为",
            )
        ):
            return False
        generic = {"人物", "角色", "神灵", "君主", "历史人物", "媒介者", "象征性人格"}
        if clean in generic:
            return False
        return bool(re.search(r"[\u4e00-\u9fff]", clean) or ALNUM_RE.search(clean))

    def _is_single_cjk_entity(self, value: str) -> bool:
        clean = str(value or "").strip()
        return len(clean) == 1 and "\u4e00" <= clean <= "\u9fff"

    def _unique(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            clean = " ".join(str(value).split()).strip()
            if (len(clean) < 2 and not self._is_single_cjk_entity(clean)) or clean in seen:
                continue
            seen.add(clean)
            result.append(clean)
        return result

    def _term_key(self, value: str) -> str:
        return re.sub(
            r"[\s\u3000,.;:!?\uff0c\u3002\uff1b\uff1a\uff01\uff1f\u3001\"'`()\[\]{}<>\u300a\u300b\-_\/]+",
            "",
            str(value or "").casefold(),
        )
