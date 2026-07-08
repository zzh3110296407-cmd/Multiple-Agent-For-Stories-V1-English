from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.memory_record import (
    MEMORY_STATUSES,
    MemoryQuery,
    MemoryQueryResponse,
    MemoryQueryResult,
    MemoryRecord,
    MemoryRecordsResponse,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.memory_index_service import MemoryIndexService
from app.backend.services.memory_migration_service import MemoryMigrationService
from app.backend.storage.json_store import JsonStore


class MemoryQueryService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.migration = MemoryMigrationService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.index_service = MemoryIndexService(store=self.store, data_dir=self.data_dir)

    def list_records(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> MemoryRecordsResponse:
        records, _warnings = self.migration.load_normalized_records()
        if status:
            records = [record for record in records if record.status == status]
        safe_limit = max(1, min(int(limit or 100), 200))
        limited = records[:safe_limit]
        return MemoryRecordsResponse(records=limited, count=len(limited))

    def get_record(self, memory_id: str) -> MemoryRecord | None:
        records, _warnings = self.migration.load_normalized_records()
        return next((record for record in records if record.memory_id == memory_id), None)

    def query(self, query: MemoryQuery) -> MemoryQueryResponse:
        records, _warnings = self.migration.load_normalized_records()
        self.index_service.build_indexes(records)
        allowed_statuses = self._allowed_statuses(query)
        results: list[MemoryQueryResult] = []
        for record in records:
            if record.status not in allowed_statuses:
                continue
            match = self._match_record(record, query)
            if not match:
                continue
            matched_by, score = match
            results.append(
                MemoryQueryResult(
                    memory_id=record.memory_id,
                    record=record,
                    matched_by=matched_by,
                    score_hint=score + (1 if record.status == "active" else 0),
                    explanation=self._explanation(record, matched_by),
                )
            )
        results.sort(key=lambda result: (-result.score_hint, result.memory_id))
        limited = results[: query.limit]
        return MemoryQueryResponse(query=query, results=limited, count=len(limited))

    def _allowed_statuses(self, query: MemoryQuery) -> set[str]:
        statuses = {
            status
            for status in (query.statuses or ["active"])
            if status in MEMORY_STATUSES
        } or {"active"}
        if query.include_provisional:
            statuses.add("provisional")
        if query.include_superseded:
            statuses.add("superseded")
        return statuses

    def _match_record(
        self,
        record: MemoryRecord,
        query: MemoryQuery,
    ) -> tuple[list[str], int] | None:
        matched_by: list[str] = []
        score = 0
        if query.chapter_id:
            if record.chapter_id != query.chapter_id:
                return None
            matched_by.append("chapter_id")
            score += 2
        if query.scene_id:
            if record.scene_id != query.scene_id:
                return None
            matched_by.append("scene_id")
            score += 3
        if query.character_ids:
            hits = self._overlap(record.character_ids, query.character_ids)
            if not hits:
                return None
            matched_by.extend([f"character_ids:{item}" for item in hits])
            score += 2
        if query.relationship_ids:
            hits = self._overlap(record.relationship_ids, query.relationship_ids)
            if not hits:
                return None
            matched_by.extend([f"relationship_ids:{item}" for item in hits])
            score += 2
        if query.event_ids:
            hits = self._overlap(record.event_ids, query.event_ids)
            if not hits:
                return None
            matched_by.extend([f"event_ids:{item}" for item in hits])
            score += 2
        if query.location:
            if self._norm(record.location) != self._norm(query.location):
                return None
            matched_by.append("location")
            score += 2
        if query.keywords:
            hits = self._keyword_hits(record, query.keywords)
            if not hits:
                return None
            matched_by.extend([f"keyword:{item}" for item in hits])
            score += len(hits)
        if query.memory_types:
            if record.memory_type not in query.memory_types:
                return None
            matched_by.append("memory_type")
        if not matched_by:
            matched_by.append("status")
        return matched_by, score

    def _keyword_hits(self, record: MemoryRecord, keywords: list[str]) -> list[str]:
        record_keywords = {self._norm(keyword) for keyword in record.keywords}
        return [
            keyword
            for keyword in keywords
            if self._norm(keyword) in record_keywords
        ]

    def _overlap(self, left: list[str], right: list[str]) -> list[str]:
        left_set = {self._norm(item) for item in left}
        return [item for item in right if self._norm(item) in left_set]

    def _norm(self, value: Any) -> str:
        return str(value or "").strip().casefold()

    def _explanation(self, record: MemoryRecord, matched_by: list[str]) -> str:
        labels: list[str] = []
        for item in matched_by:
            if item == "chapter_id":
                labels.append("章节")
            elif item == "scene_id":
                labels.append("场景")
            elif item.startswith("character_ids:"):
                labels.append(f"角色 {item.split(':', 1)[1]}")
            elif item.startswith("relationship_ids:"):
                labels.append(f"关系 {item.split(':', 1)[1]}")
            elif item.startswith("event_ids:"):
                labels.append(f"事件 {item.split(':', 1)[1]}")
            elif item == "location":
                labels.append("地点")
            elif item.startswith("keyword:"):
                labels.append(f"关键词 {item.split(':', 1)[1]}")
            elif item == "memory_type":
                labels.append("记忆类型")
            elif item == "status":
                labels.append("状态")
        status_note = f"当前状态为 {record.status}。"
        if record.status == "provisional":
            status_note = "这是 provisional 临时记忆，只在显式请求时返回。"
        elif record.status == "superseded":
            status_note = "这是 superseded 旧记忆，只在显式请求时返回。"
        return f"匹配原因：{'、'.join(labels)}。{status_note}"
