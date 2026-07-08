# Storage Port Contract v0 - 2026-07-04

## Purpose

This contract defines the Database-session prototype boundary. It mirrors the current backend repository shape while reserving PostgreSQL modes and shadow validation.

No main backend code imports this file during M0/M1.

## Storage Modes

| Mode | Meaning |
| --- | --- |
| `JSON_PRIMARY` | Existing runtime writes JSON first. |
| `POSTGRES_SHADOW` | JSON remains primary; PostgreSQL receives imports or mirrored writes for comparison. |
| `POSTGRES_PRIMARY` | PostgreSQL is primary for new project writes. |
| `JSON_EXPORT_ONLY` | JSON is generated from PostgreSQL for backup, fixture or portability. |

## Repository Contract

Minimum behavior copied from current backend protocols:

```text
list_all(project_id, filters) -> rows
get_by_business_id(project_id, business_id) -> row | null
append(project_id, row, idempotency_key) -> row
upsert(project_id, business_id, row, idempotency_key) -> row
write_all(project_id, rows, batch_id) -> write_result
```

Pack repositories additionally expose:

```text
read_pack(pack_id)
list_packs(project_id, filters)
write_pack(project_id, pack, dependency_refs)
mark_pack_stale(project_id, pack_id, stale_reason)
```

## Required Repository Families For M1

- `ProjectRepository`
- `StorageAssignmentRepository`
- `MemoryRepository`
- `ChapterRepository`
- `SceneRepository`
- `CharacterRepository`
- `DecisionRepository`
- `ChapterMemoryPackRepository`
- `SceneMemoryPackRepository`
- `MigrationRepository`

## Shadow Validation Contract

Every shadow import or shadow write records:

- source path or source operation id;
- source hash;
- project id;
- target domain;
- target row count;
- idempotency key;
- canonical status mapping;
- content hash;
- mismatches by category.

Minimum mismatch categories:

- `missing_project_id`
- `duplicate_business_id`
- `duplicate_idempotency_key`
- `status_mapping_drift`
- `foreign_key_missing`
- `current_draft_pointer_invalid`
- `pack_dependency_missing`
- `search_document_stale`
- `superseded_node_used_as_active`
- `secret_like_value_detected`

## Transaction Boundaries

The PostgreSQL adapter must support explicit transactions for:

- accepting a scene draft;
- applying user revision;
- writing events, state changes and memory records;
- updating search documents/cards;
- invalidating packs;
- formal apply execution;
- importing one JSON batch.

Partial success is failure unless the operation is explicitly a staged candidate.

