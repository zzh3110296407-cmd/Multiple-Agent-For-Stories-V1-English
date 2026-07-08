-- Smoke checks for Phase 8.75 M2B schema migrations.
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
) VALUES (
  'project_m2b_smoke_001',
  'M2B Smoke Project',
  'zh',
  'POSTGRES_SHADOW',
  'DRAFT',
  'm2b_smoke',
  'ACTIVE',
  'USER_CONFIRMED',
  'm2b:project:001',
  'SYSTEM'
)
ON CONFLICT (project_id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  updated_at = now();

INSERT INTO chapters (project_id, chapter_id, chapter_number, title, status)
SELECT id, 'chapter_m2b_001', 101, 'M2B Smoke Chapter', 'DRAFT'
FROM projects
WHERE project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, chapter_id) DO UPDATE SET
  title = EXCLUDED.title,
  updated_at = now();

INSERT INTO scenes (project_id, scene_id, chapter_id, scene_order, scene_title, status)
SELECT p.id, 'scene_m2b_001', c.id, 1, 'M2B Smoke Scene', 'DRAFT'
FROM projects p
JOIN chapters c ON c.project_id = p.id AND c.chapter_id = 'chapter_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, scene_id) DO UPDATE SET
  scene_title = EXCLUDED.scene_title,
  updated_at = now();

INSERT INTO events (project_id, event_id, scene_id, event_type, event_summary, status)
SELECT p.id, 'event_m2b_001', s.id, 'SCENE_EVENT', 'M2B smoke event.', 'DRAFT'
FROM projects p
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, event_id) DO UPDATE SET
  event_summary = EXCLUDED.event_summary,
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
SELECT p.id, 'memory_m2b_001', s.id, e.id, 'OBJECTIVE', 'SCENE_FACT', 'M2B smoke memory.', 'DRAFT'
FROM projects p
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m2b_001'
JOIN events e ON e.project_id = p.id AND e.event_id = 'event_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, memory_id) DO UPDATE SET
  memory_text = EXCLUDED.memory_text,
  updated_at = now();

INSERT INTO memory_links (
  project_id,
  memory_link_id,
  memory_id,
  linked_entity_type,
  linked_business_id,
  link_role,
  status
)
SELECT p.id, 'memory_link_m2b_001', m.id, 'scene', 'scene_m2b_001', 'evidence', 'DRAFT'
FROM projects p
JOIN memory_records m ON m.project_id = p.id AND m.memory_id = 'memory_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, memory_link_id) DO UPDATE SET
  link_role = EXCLUDED.link_role,
  updated_at = now();

INSERT INTO memory_packs (
  project_id,
  memory_pack_id,
  chapter_id,
  scene_id,
  pack_type,
  pack_scope,
  status
)
SELECT p.id, 'memory_pack_m2b_001', c.id, s.id, 'SCENE', 'scene_m2b_001', 'DRAFT'
FROM projects p
JOIN chapters c ON c.project_id = p.id AND c.chapter_id = 'chapter_m2b_001'
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, memory_pack_id) DO UPDATE SET
  pack_scope = EXCLUDED.pack_scope,
  updated_at = now();

INSERT INTO memory_pack_items (
  project_id,
  memory_pack_item_id,
  memory_pack_id,
  memory_id,
  item_order,
  item_role,
  inclusion_reason,
  status
)
SELECT p.id, 'memory_pack_item_m2b_001', mp.id, m.id, 1, 'required_context', 'M2B smoke dependency path', 'DRAFT'
FROM projects p
JOIN memory_packs mp ON mp.project_id = p.id AND mp.memory_pack_id = 'memory_pack_m2b_001'
JOIN memory_records m ON m.project_id = p.id AND m.memory_id = 'memory_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, memory_pack_item_id) DO UPDATE SET
  inclusion_reason = EXCLUDED.inclusion_reason,
  updated_at = now();

INSERT INTO memory_pack_dependencies (
  project_id,
  memory_pack_dependency_id,
  memory_pack_id,
  dependency_entity_type,
  dependency_business_id,
  dependency_reason,
  status
)
SELECT p.id, 'memory_pack_dependency_m2b_001', mp.id, 'scene', 'scene_m2b_001', 'pack depends on scene freshness', 'DRAFT'
FROM projects p
JOIN memory_packs mp ON mp.project_id = p.id AND mp.memory_pack_id = 'memory_pack_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, memory_pack_dependency_id) DO UPDATE SET
  dependency_reason = EXCLUDED.dependency_reason,
  updated_at = now();

INSERT INTO gate_runs (project_id, gate_run_id, scene_id, gate_name, gate_result, status)
SELECT p.id, 'gate_run_m2b_001', s.id, 'm2b_quality_gate', 'PENDING', 'DRAFT'
FROM projects p
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, gate_run_id) DO UPDATE SET
  gate_result = EXCLUDED.gate_result,
  updated_at = now();

INSERT INTO quality_reports (
  project_id,
  quality_report_id,
  scene_id,
  gate_run_id,
  report_type,
  report_result,
  summary,
  status
)
SELECT p.id, 'quality_report_m2b_001', s.id, g.id, 'SCENE_QUALITY', 'PENDING', 'M2B quality smoke.', 'DRAFT'
FROM projects p
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m2b_001'
JOIN gate_runs g ON g.project_id = p.id AND g.gate_run_id = 'gate_run_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, quality_report_id) DO UPDATE SET
  summary = EXCLUDED.summary,
  updated_at = now();

INSERT INTO continuity_issues (
  project_id,
  continuity_issue_id,
  quality_report_id,
  scene_id,
  issue_type,
  severity,
  issue_text,
  status
)
SELECT p.id, 'continuity_issue_m2b_001', qr.id, s.id, 'TIMELINE', 'LOW', 'M2B continuity smoke.', 'CANDIDATE'
FROM projects p
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m2b_001'
JOIN quality_reports qr ON qr.project_id = p.id AND qr.quality_report_id = 'quality_report_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, continuity_issue_id) DO UPDATE SET
  issue_text = EXCLUDED.issue_text,
  updated_at = now();

INSERT INTO claim_records (
  project_id,
  claim_id,
  scene_id,
  speaker_entity_type,
  speaker_business_id,
  claim_text,
  truth_status,
  status
)
SELECT p.id, 'claim_m2b_001', s.id, 'character', 'character_m2b_001', 'M2B claim record smoke.', 'UNKNOWN', 'CANDIDATE'
FROM projects p
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, claim_id) DO UPDATE SET
  claim_text = EXCLUDED.claim_text,
  updated_at = now();

INSERT INTO perception_states (
  project_id,
  perception_id,
  source_scene_id,
  character_business_id,
  target_entity_type,
  target_business_id,
  perceived_fact,
  confidence,
  status
)
SELECT p.id, 'perception_m2b_001', s.id, 'character_m2b_001', 'scene', 'scene_m2b_001', 'M2B perception smoke.', 0.750, 'CANDIDATE'
FROM projects p
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, perception_id) DO UPDATE SET
  perceived_fact = EXCLUDED.perceived_fact,
  updated_at = now();

INSERT INTO character_psychology_traces (
  project_id,
  trace_id,
  scene_id,
  character_business_id,
  internal_state,
  visibility,
  status
)
SELECT p.id, 'trace_m2b_001', s.id, 'character_m2b_001', 'M2B psychology smoke.', 'PRIVATE', 'CANDIDATE'
FROM projects p
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, trace_id) DO UPDATE SET
  internal_state = EXCLUDED.internal_state,
  updated_at = now();

INSERT INTO character_expression_records (
  project_id,
  expression_id,
  scene_id,
  character_business_id,
  expression_text,
  status
)
SELECT p.id, 'expression_m2b_001', s.id, 'character_m2b_001', 'M2B expression smoke.', 'CANDIDATE'
FROM projects p
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, expression_id) DO UPDATE SET
  expression_text = EXCLUDED.expression_text,
  updated_at = now();

INSERT INTO narrative_intents (
  project_id,
  intent_id,
  target_ref,
  intent_type,
  description,
  status
)
SELECT p.id, 'intent_m2b_001', '{"type":"scene","business_id":"scene_m2b_001"}'::jsonb, 'AMBIGUITY', 'M2B narrative intent smoke.', 'CANDIDATE'
FROM projects p
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, intent_id) DO UPDATE SET
  description = EXCLUDED.description,
  updated_at = now();

INSERT INTO apparent_contradictions (
  project_id,
  contradiction_id,
  scene_id,
  narrative_intent_id,
  contradiction_text,
  classification,
  status
)
SELECT p.id, 'contradiction_m2b_001', s.id, ni.id, 'M2B contradiction smoke.', 'INTENTIONAL', 'CANDIDATE'
FROM projects p
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m2b_001'
JOIN narrative_intents ni ON ni.project_id = p.id AND ni.intent_id = 'intent_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, contradiction_id) DO UPDATE SET
  contradiction_text = EXCLUDED.contradiction_text,
  updated_at = now();

INSERT INTO narrative_debts (
  project_id,
  debt_id,
  chapter_id,
  setup_scene_id,
  debt_type,
  debt_text,
  payoff_plan,
  status
)
SELECT p.id, 'debt_m2b_001', c.id, s.id, 'PROMISE', 'M2B narrative debt smoke.', 'Resolve in a later scene.', 'CANDIDATE'
FROM projects p
JOIN chapters c ON c.project_id = p.id AND c.chapter_id = 'chapter_m2b_001'
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m2b_001'
WHERE p.project_id = 'project_m2b_smoke_001'
ON CONFLICT (project_id, debt_id) DO UPDATE SET
  debt_text = EXCLUDED.debt_text,
  updated_at = now();

DO $$
DECLARE
  pack_dependency_rows integer;
  quality_rows integer;
  subjective_rows integer;
BEGIN
  SELECT count(*) INTO pack_dependency_rows
  FROM memory_pack_dependencies mpd
  JOIN projects p ON p.id = mpd.project_id
  WHERE p.project_id = 'project_m2b_smoke_001'
    AND mpd.memory_pack_dependency_id = 'memory_pack_dependency_m2b_001'
    AND mpd.dependency_entity_type = 'scene';

  IF pack_dependency_rows <> 1 THEN
    RAISE EXCEPTION 'Expected one memory pack dependency row, got %', pack_dependency_rows;
  END IF;

  SELECT count(*) INTO quality_rows
  FROM quality_reports qr
  JOIN continuity_issues ci ON ci.quality_report_id = qr.id AND ci.project_id = qr.project_id
  JOIN projects p ON p.id = qr.project_id
  WHERE p.project_id = 'project_m2b_smoke_001'
    AND qr.quality_report_id = 'quality_report_m2b_001'
    AND ci.continuity_issue_id = 'continuity_issue_m2b_001';

  IF quality_rows <> 1 THEN
    RAISE EXCEPTION 'Expected quality/continuity path row, got %', quality_rows;
  END IF;

  SELECT count(*) INTO subjective_rows
  FROM claim_records cr
  JOIN perception_states ps ON ps.project_id = cr.project_id
  JOIN character_psychology_traces cpt ON cpt.project_id = cr.project_id
  JOIN character_expression_records cer ON cer.project_id = cr.project_id
  JOIN narrative_intents ni ON ni.project_id = cr.project_id
  JOIN apparent_contradictions ac ON ac.project_id = cr.project_id AND ac.narrative_intent_id = ni.id
  JOIN narrative_debts nd ON nd.project_id = cr.project_id
  JOIN projects p ON p.id = cr.project_id
  WHERE p.project_id = 'project_m2b_smoke_001'
    AND cr.claim_id = 'claim_m2b_001'
    AND ps.perception_id = 'perception_m2b_001'
    AND cpt.trace_id = 'trace_m2b_001'
    AND cer.expression_id = 'expression_m2b_001'
    AND ni.intent_id = 'intent_m2b_001'
    AND ac.contradiction_id = 'contradiction_m2b_001'
    AND nd.debt_id = 'debt_m2b_001';

  IF subjective_rows <> 1 THEN
    RAISE EXCEPTION 'Expected subjective records path row, got %', subjective_rows;
  END IF;
END $$;

DO $$
DECLARE
  project_a uuid;
  project_b uuid;
  cross_memory_id uuid;
BEGIN
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
      'project_m2b_cross_a',
      'M2B Cross Project A',
      'zh',
      'POSTGRES_SHADOW',
      'DRAFT',
      'm2b_cross',
      'ACTIVE',
      'USER_CONFIRMED',
      'm2b:cross:a',
      'SYSTEM'
    ),
    (
      'project_m2b_cross_b',
      'M2B Cross Project B',
      'zh',
      'POSTGRES_SHADOW',
      'DRAFT',
      'm2b_cross',
      'ACTIVE',
      'USER_CONFIRMED',
      'm2b:cross:b',
      'SYSTEM'
    )
  ON CONFLICT (project_id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    updated_at = now();

  SELECT id INTO project_a FROM projects WHERE project_id = 'project_m2b_cross_a';
  SELECT id INTO project_b FROM projects WHERE project_id = 'project_m2b_cross_b';

  INSERT INTO memory_records (
    project_id,
    memory_id,
    memory_lane,
    memory_type,
    memory_text,
    status
  ) VALUES (
    project_a,
    'memory_m2b_cross_001',
    'OBJECTIVE',
    'SCENE_FACT',
    'Cross-project FK rejection source memory.',
    'DRAFT'
  )
  ON CONFLICT (project_id, memory_id) DO UPDATE SET
    memory_text = EXCLUDED.memory_text,
    updated_at = now();

  SELECT id INTO cross_memory_id
  FROM memory_records
  WHERE project_id = project_a
    AND memory_id = 'memory_m2b_cross_001';

  BEGIN
    INSERT INTO memory_links (
      project_id,
      memory_link_id,
      memory_id,
      linked_entity_type,
      linked_business_id,
      link_role,
      status
    ) VALUES (
      project_b,
      'memory_link_m2b_cross_forbidden',
      cross_memory_id,
      'memory',
      'memory_m2b_cross_001',
      'forbidden_cross_project',
      'DRAFT'
    );

    RAISE EXCEPTION 'Expected cross-project memory_links FK rejection';
  EXCEPTION
    WHEN foreign_key_violation THEN
      NULL;
  END;
END $$;

ROLLBACK;
