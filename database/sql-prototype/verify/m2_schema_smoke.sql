-- Smoke checks for Phase 8.75 M2A schema migrations.
-- The data writes are rolled back; schema objects remain from migrations.

\set ON_ERROR_STOP on

SET search_path TO mas_phase875_proto;

BEGIN;

INSERT INTO projects (
  project_id,
  display_name,
  language,
  storage_mode,
  status,
  legacy_status_raw,
  lifecycle_state,
  authority_level,
  idempotency_key,
  source_type
) VALUES
  (
    'project_m2_smoke_001',
    'M2 Smoke Project',
    'zh',
    'POSTGRES_SHADOW',
    'DRAFT',
    'm2_smoke',
    'ACTIVE',
    'USER_CONFIRMED',
    'm2:project:001',
    'SYSTEM'
  ),
  (
    'project_m2_smoke_002',
    'M2 Smoke Project 2',
    'zh',
    'POSTGRES_SHADOW',
    'DRAFT',
    'm2_smoke',
    'ACTIVE',
    'USER_CONFIRMED',
    'm2:project:002',
    'SYSTEM'
  )
ON CONFLICT (project_id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  updated_at = now();

INSERT INTO project_story_premises (project_id, premise_id, premise_text, status)
SELECT id, 'premise_001', 'A project-scoped M2 smoke premise.', 'DRAFT'
FROM projects
WHERE project_id = 'project_m2_smoke_001'
ON CONFLICT (project_id, premise_id) DO UPDATE SET
  premise_text = EXCLUDED.premise_text,
  updated_at = now();

INSERT INTO world_canvases (project_id, canvas_id, canvas_name, status)
SELECT id, 'world_001', 'M2 Smoke World', 'DRAFT'
FROM projects
WHERE project_id = 'project_m2_smoke_001'
ON CONFLICT (project_id, canvas_id) DO UPDATE SET
  canvas_name = EXCLUDED.canvas_name,
  updated_at = now();

INSERT INTO characters (project_id, character_id, display_name, role_tier, status)
SELECT id, 'character_001', 'Smoke Character', 'PROTAGONIST', 'DRAFT'
FROM projects
WHERE project_id = 'project_m2_smoke_001'
ON CONFLICT (project_id, character_id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  updated_at = now();

INSERT INTO framework_packages (project_id, framework_package_id, package_name, status)
SELECT id, 'framework_001', 'Smoke Framework', 'DRAFT'
FROM projects
WHERE project_id = 'project_m2_smoke_001'
ON CONFLICT (project_id, framework_package_id) DO UPDATE SET
  package_name = EXCLUDED.package_name,
  updated_at = now();

INSERT INTO chapters (project_id, chapter_id, chapter_number, title, status)
SELECT id, 'chapter_001', 1, 'Smoke Chapter', 'DRAFT'
FROM projects
WHERE project_id = 'project_m2_smoke_001'
ON CONFLICT (project_id, chapter_id) DO UPDATE SET
  title = EXCLUDED.title,
  updated_at = now();

INSERT INTO scenes (project_id, scene_id, chapter_id, scene_order, scene_title, status)
SELECT p.id, 'scene_001', c.id, 1, 'Smoke Scene', 'DRAFT'
FROM projects p
JOIN chapters c ON c.project_id = p.id AND c.chapter_id = 'chapter_001'
WHERE p.project_id = 'project_m2_smoke_001'
ON CONFLICT (project_id, scene_id) DO UPDATE SET
  scene_title = EXCLUDED.scene_title,
  updated_at = now();

INSERT INTO scenes (project_id, scene_id, scene_order, scene_title, status)
SELECT id, 'scene_001', 1, 'Same business id in different project', 'DRAFT'
FROM projects
WHERE project_id = 'project_m2_smoke_002'
ON CONFLICT (project_id, scene_id) DO UPDATE SET
  scene_title = EXCLUDED.scene_title,
  updated_at = now();

INSERT INTO scene_drafts (project_id, draft_id, scene_id, draft_text, status)
SELECT p.id, 'draft_001', s.id, 'Smoke draft text.', 'DRAFT'
FROM projects p
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_001'
WHERE p.project_id = 'project_m2_smoke_001'
ON CONFLICT (project_id, draft_id) DO UPDATE SET
  draft_text = EXCLUDED.draft_text,
  updated_at = now();

INSERT INTO events (project_id, event_id, scene_id, event_type, event_summary, status)
SELECT p.id, 'event_001', s.id, 'SCENE_EVENT', 'Smoke event.', 'DRAFT'
FROM projects p
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_001'
WHERE p.project_id = 'project_m2_smoke_001'
ON CONFLICT (project_id, event_id) DO UPDATE SET
  event_summary = EXCLUDED.event_summary,
  updated_at = now();

INSERT INTO decisions (project_id, decision_id, decision_type, decision_text, status)
SELECT id, 'decision_001', 'FORMAL_APPLY', 'Smoke decision.', 'DRAFT'
FROM projects
WHERE project_id = 'project_m2_smoke_001'
ON CONFLICT (project_id, decision_id) DO UPDATE SET
  decision_text = EXCLUDED.decision_text,
  updated_at = now();

INSERT INTO gate_runs (project_id, gate_run_id, gate_name, gate_result, status)
SELECT id, 'gate_run_001', 'm2_smoke_gate', 'PENDING', 'DRAFT'
FROM projects
WHERE project_id = 'project_m2_smoke_001'
ON CONFLICT (project_id, gate_run_id) DO UPDATE SET
  gate_result = EXCLUDED.gate_result,
  updated_at = now();

INSERT INTO memory_records (
  project_id,
  memory_id,
  scene_id,
  event_id,
  memory_lane,
  memory_type,
  memory_text,
  status
)
SELECT p.id, 'memory_001', s.id, e.id, 'OBJECTIVE', 'SCENE_FACT', 'Smoke memory.', 'DRAFT'
FROM projects p
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_001'
JOIN events e ON e.project_id = p.id AND e.event_id = 'event_001'
WHERE p.project_id = 'project_m2_smoke_001'
ON CONFLICT (project_id, memory_id) DO UPDATE SET
  memory_text = EXCLUDED.memory_text,
  updated_at = now();

DO $$
DECLARE
  scene_rows integer;
  memory_rows integer;
  cross_project_scene_rows integer;
BEGIN
  SELECT count(*) INTO scene_rows
  FROM scenes s
  JOIN projects p ON p.id = s.project_id
  WHERE p.project_id = 'project_m2_smoke_001'
    AND s.scene_id = 'scene_001'
    AND s.status = 'DRAFT'
    AND s.lifecycle_state = 'ACTIVE';

  IF scene_rows <> 1 THEN
    RAISE EXCEPTION 'Expected one M2 smoke scene row for project 1, got %', scene_rows;
  END IF;

  SELECT count(*) INTO cross_project_scene_rows
  FROM scenes
  WHERE scene_id = 'scene_001';

  IF cross_project_scene_rows <> 2 THEN
    RAISE EXCEPTION 'Expected project-scoped scene business ids to allow two rows, got %', cross_project_scene_rows;
  END IF;

  SELECT count(*) INTO memory_rows
  FROM memory_records m
  JOIN projects p ON p.id = m.project_id
  WHERE p.project_id = 'project_m2_smoke_001'
    AND m.memory_id = 'memory_001'
    AND m.memory_lane = 'OBJECTIVE';

  IF memory_rows <> 1 THEN
    RAISE EXCEPTION 'Expected one M2 smoke memory row, got %', memory_rows;
  END IF;
END $$;

DO $$
DECLARE
  project_2_id uuid;
  project_1_scene_id uuid;
BEGIN
  SELECT id INTO project_2_id
  FROM projects
  WHERE project_id = 'project_m2_smoke_002';

  SELECT s.id INTO project_1_scene_id
  FROM scenes s
  JOIN projects p ON p.id = s.project_id
  WHERE p.project_id = 'project_m2_smoke_001'
    AND s.scene_id = 'scene_001';

  BEGIN
    INSERT INTO scene_drafts (
      project_id,
      draft_id,
      scene_id,
      draft_text,
      status
    ) VALUES (
      project_2_id,
      'draft_cross_project_forbidden',
      project_1_scene_id,
      'This draft must not reference another project scene.',
      'DRAFT'
    );

    RAISE EXCEPTION 'Expected cross-project M2A scene_drafts FK rejection';
  EXCEPTION
    WHEN foreign_key_violation THEN
      NULL;
  END;
END $$;

ROLLBACK;
