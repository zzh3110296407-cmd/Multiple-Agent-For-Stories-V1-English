-- Smoke checks for Phase 8.75 M3 retrieval and timeline foundation.
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
  'project_m3_smoke_001',
  'M3 Smoke Project',
  'zh',
  'POSTGRES_SHADOW',
  'DRAFT',
  'm3_smoke',
  'ACTIVE',
  'USER_CONFIRMED',
  'm3:project:001',
  'SYSTEM'
)
ON CONFLICT (project_id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  updated_at = now();

INSERT INTO chapters (project_id, chapter_id, chapter_number, title, status)
SELECT id, 'chapter_m3_001', 301, 'M3 Smoke Chapter', 'DRAFT'
FROM projects
WHERE project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, chapter_id) DO UPDATE SET
  title = EXCLUDED.title,
  updated_at = now();

INSERT INTO scenes (project_id, scene_id, chapter_id, scene_order, scene_title, status)
SELECT p.id, 'scene_m3_001', c.id, 1, 'M3 Smoke Scene', 'DRAFT'
FROM projects p
JOIN chapters c ON c.project_id = p.id AND c.chapter_id = 'chapter_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, scene_id) DO UPDATE SET
  scene_title = EXCLUDED.scene_title,
  updated_at = now();

INSERT INTO characters (project_id, character_id, display_name, role_tier, status)
SELECT id, 'character_m3_001', 'M3 Character', 'POV', 'DRAFT'
FROM projects
WHERE project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, character_id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  updated_at = now();

INSERT INTO world_locations (project_id, location_id, location_name, location_type, description, status)
SELECT id, 'location_m3_001', 'M3 Location', 'ROOM', 'M3 location state smoke.', 'DRAFT'
FROM projects
WHERE project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, location_id) DO UPDATE SET
  location_name = EXCLUDED.location_name,
  updated_at = now();

INSERT INTO events (project_id, event_id, scene_id, chapter_id, event_type, event_summary, event_order, status)
SELECT p.id, 'event_m3_001', s.id, c.id, 'SCENE_EVENT', 'M3 smoke event.', 1, 'DRAFT'
FROM projects p
JOIN chapters c ON c.project_id = p.id AND c.chapter_id = 'chapter_m3_001'
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, event_id) DO UPDATE SET
  event_summary = EXCLUDED.event_summary,
  updated_at = now();

INSERT INTO memory_records (
  project_id,
  memory_id,
  scene_id,
  chapter_id,
  event_id,
  memory_lane,
  memory_type,
  subject_entity_type,
  subject_business_id,
  memory_text,
  visibility_scope,
  status
)
SELECT p.id, 'memory_m3_001', s.id, c.id, e.id, 'OBJECTIVE', 'SCENE_FACT', 'character', 'character_m3_001', 'M3 smoke memory.', 'SCENE', 'DRAFT'
FROM projects p
JOIN chapters c ON c.project_id = p.id AND c.chapter_id = 'chapter_m3_001'
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m3_001'
JOIN events e ON e.project_id = p.id AND e.event_id = 'event_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, memory_id) DO UPDATE SET
  memory_text = EXCLUDED.memory_text,
  updated_at = now();

INSERT INTO retrieval_task_specs (
  project_id,
  retrieval_task_id,
  chapter_id,
  scene_id,
  agent_role,
  task_type,
  query_text,
  max_items,
  token_budget,
  status
)
SELECT p.id, 'retrieval_task_m3_001', c.id, s.id, 'WriterAgent', 'SCENE_PACK_BUILD', 'Build a safe scene context pack.', 20, 2000, 'DRAFT'
FROM projects p
JOIN chapters c ON c.project_id = p.id AND c.chapter_id = 'chapter_m3_001'
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, retrieval_task_id) DO UPDATE SET
  query_text = EXCLUDED.query_text,
  updated_at = now();

INSERT INTO search_documents (
  project_id,
  search_document_id,
  entity_type,
  entity_business_id,
  entity_physical_id,
  title,
  summary,
  search_text,
  importance,
  status
)
SELECT p.id, 'search_document_m3_001', 'memory', 'memory_m3_001', m.id, 'M3 memory card', 'M3 retrieval summary.', 'M3 smoke memory searchable text.', 0.900, 'CONFIRMED'
FROM projects p
JOIN memory_records m ON m.project_id = p.id AND m.memory_id = 'memory_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, search_document_id) DO UPDATE SET
  summary = EXCLUDED.summary,
  updated_at = now();

INSERT INTO entity_aliases (project_id, entity_alias_id, entity_type, entity_business_id, alias_text, alias_type, status)
SELECT id, 'entity_alias_m3_001', 'character', 'character_m3_001', 'M3 Alias', 'nickname', 'CONFIRMED'
FROM projects
WHERE project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, entity_alias_id) DO UPDATE SET
  alias_text = EXCLUDED.alias_text,
  updated_at = now();

INSERT INTO entity_keywords (project_id, entity_keyword_id, entity_type, entity_business_id, keyword, keyword_type, weight, status)
SELECT id, 'entity_keyword_m3_001', 'memory', 'memory_m3_001', 'm3-keyword', 'scene', 1.000, 'CONFIRMED'
FROM projects
WHERE project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, entity_keyword_id) DO UPDATE SET
  keyword = EXCLUDED.keyword,
  updated_at = now();

INSERT INTO entity_tags (project_id, entity_tag_id, entity_type, entity_business_id, tag, tag_type, status)
SELECT id, 'entity_tag_m3_001', 'memory', 'memory_m3_001', 'continuity', 'purpose', 'CONFIRMED'
FROM projects
WHERE project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, entity_tag_id) DO UPDATE SET
  tag = EXCLUDED.tag,
  updated_at = now();

INSERT INTO entity_links (
  project_id,
  entity_link_id,
  source_entity_type,
  source_business_id,
  target_entity_type,
  target_business_id,
  link_type,
  directionality,
  status
)
SELECT id, 'entity_link_m3_001', 'memory', 'memory_m3_001', 'scene', 'scene_m3_001', 'located_at', 'DIRECTED', 'CONFIRMED'
FROM projects
WHERE project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, entity_link_id) DO UPDATE SET
  link_type = EXCLUDED.link_type,
  updated_at = now();

INSERT INTO memory_entity_links (project_id, memory_entity_link_id, memory_id, entity_type, entity_business_id, link_role, status)
SELECT p.id, 'memory_entity_link_m3_001', m.id, 'character', 'character_m3_001', 'subject', 'CONFIRMED'
FROM projects p
JOIN memory_records m ON m.project_id = p.id AND m.memory_id = 'memory_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, memory_entity_link_id) DO UPDATE SET
  link_role = EXCLUDED.link_role,
  updated_at = now();

INSERT INTO memory_tags (project_id, memory_tag_id, memory_id, tag, tag_type, status)
SELECT p.id, 'memory_tag_m3_001', m.id, 'm3-memory-tag', 'continuity', 'CONFIRMED'
FROM projects p
JOIN memory_records m ON m.project_id = p.id AND m.memory_id = 'memory_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, memory_tag_id) DO UPDATE SET
  tag = EXCLUDED.tag,
  updated_at = now();

INSERT INTO chapter_memory_packs (
  project_id,
  chapter_memory_pack_id,
  chapter_id,
  pack_purpose,
  dependency_refs,
  dependency_hash,
  freshness_status,
  last_built_at,
  status
)
SELECT p.id, 'chapter_pack_m3_001', c.id, 'M3 chapter retrieval pack', '[{"type":"chapter","business_id":"chapter_m3_001"}]'::jsonb, 'm3-chapter-hash', 'FRESH', now(), 'CONFIRMED'
FROM projects p
JOIN chapters c ON c.project_id = p.id AND c.chapter_id = 'chapter_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, chapter_memory_pack_id) DO UPDATE SET
  freshness_status = EXCLUDED.freshness_status,
  updated_at = now();

INSERT INTO scene_memory_packs (
  project_id,
  scene_memory_pack_id,
  chapter_pack_id,
  scene_id,
  pack_purpose,
  dependency_refs,
  dependency_hash,
  freshness_status,
  last_built_at,
  status
)
SELECT p.id, 'scene_pack_m3_001', cp.id, s.id, 'M3 scene retrieval pack', '[{"type":"scene","business_id":"scene_m3_001"}]'::jsonb, 'm3-scene-hash', 'FRESH', now(), 'CONFIRMED'
FROM projects p
JOIN chapter_memory_packs cp ON cp.project_id = p.id AND cp.chapter_memory_pack_id = 'chapter_pack_m3_001'
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, scene_memory_pack_id) DO UPDATE SET
  freshness_status = EXCLUDED.freshness_status,
  updated_at = now();

INSERT INTO agent_context_packs (
  project_id,
  agent_context_pack_id,
  scene_pack_id,
  retrieval_task_id,
  agent_role,
  pack_purpose,
  dependency_refs,
  dependency_hash,
  freshness_status,
  last_built_at,
  status
)
SELECT p.id, 'agent_pack_m3_001', sp.id, rt.id, 'WriterAgent', 'M3 WriterAgent context pack', '[{"type":"scene_pack","business_id":"scene_pack_m3_001"}]'::jsonb, 'm3-agent-hash', 'FRESH', now(), 'CONFIRMED'
FROM projects p
JOIN scene_memory_packs sp ON sp.project_id = p.id AND sp.scene_memory_pack_id = 'scene_pack_m3_001'
JOIN retrieval_task_specs rt ON rt.project_id = p.id AND rt.retrieval_task_id = 'retrieval_task_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, agent_context_pack_id) DO UPDATE SET
  freshness_status = EXCLUDED.freshness_status,
  updated_at = now();

INSERT INTO pack_items (
  project_id,
  pack_item_id,
  agent_context_pack_id,
  search_document_id,
  memory_id,
  pack_type,
  item_order,
  entity_type,
  entity_business_id,
  reason,
  rank_score,
  token_estimate,
  required_for_generation,
  access_label,
  source_status,
  included_in_writer_context,
  status
)
SELECT p.id, 'pack_item_m3_001', ap.id, sd.id, m.id, 'AGENT', 1, 'memory', 'memory_m3_001', 'USABLE_NOW memory for WriterAgent.', 0.9500, 80, true, 'USABLE_NOW', 'CONFIRMED', true, 'CONFIRMED'
FROM projects p
JOIN agent_context_packs ap ON ap.project_id = p.id AND ap.agent_context_pack_id = 'agent_pack_m3_001'
JOIN search_documents sd ON sd.project_id = p.id AND sd.search_document_id = 'search_document_m3_001'
JOIN memory_records m ON m.project_id = p.id AND m.memory_id = 'memory_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, pack_item_id) DO UPDATE SET
  reason = EXCLUDED.reason,
  updated_at = now();

INSERT INTO retrieval_usage_records (
  project_id,
  retrieval_usage_id,
  retrieval_task_id,
  scene_pack_id,
  agent_context_pack_id,
  query_text,
  candidate_count,
  selected_count,
  used_entity_refs,
  missing_requirements,
  latency_ms,
  token_estimate,
  status
)
SELECT p.id, 'retrieval_usage_m3_001', rt.id, sp.id, ap.id, 'Build a safe scene context pack.', 2, 1, '[{"type":"memory","business_id":"memory_m3_001"}]'::jsonb, '[]'::jsonb, 12, 80, 'CONFIRMED'
FROM projects p
JOIN retrieval_task_specs rt ON rt.project_id = p.id AND rt.retrieval_task_id = 'retrieval_task_m3_001'
JOIN scene_memory_packs sp ON sp.project_id = p.id AND sp.scene_memory_pack_id = 'scene_pack_m3_001'
JOIN agent_context_packs ap ON ap.project_id = p.id AND ap.agent_context_pack_id = 'agent_pack_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, retrieval_usage_id) DO UPDATE SET
  selected_count = EXCLUDED.selected_count,
  updated_at = now();

INSERT INTO retrieval_gap_records (
  project_id,
  retrieval_gap_id,
  retrieval_task_id,
  scene_id,
  gap_type,
  claim_text,
  searched_scopes,
  recommended_resolution,
  status
)
SELECT p.id, 'retrieval_gap_m3_001', rt.id, s.id, 'MISSING_STATE', 'Expected but missing optional location mood.', '["scene","memory","timeline"]'::jsonb, 'Ask user or create candidate state.', 'CANDIDATE'
FROM projects p
JOIN retrieval_task_specs rt ON rt.project_id = p.id AND rt.retrieval_task_id = 'retrieval_task_m3_001'
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, retrieval_gap_id) DO UPDATE SET
  claim_text = EXCLUDED.claim_text,
  updated_at = now();

INSERT INTO timelines (project_id, timeline_id, timeline_type, timeline_summary, status)
SELECT id, 'timeline_m3_main', 'MAIN', 'M3 main timeline smoke.', 'CONFIRMED'
FROM projects
WHERE project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, timeline_id) DO UPDATE SET
  timeline_summary = EXCLUDED.timeline_summary,
  updated_at = now();

INSERT INTO character_memory_nodes (
  project_id,
  character_memory_node_id,
  character_id,
  timeline_id,
  source_scene_id,
  source_event_id,
  experienced_at,
  experienced_at_sort_key,
  known_at,
  known_at_sort_key,
  narrative_recorded_at,
  narrative_recorded_at_sort_key,
  valid_from,
  valid_from_sort_key,
  valid_to,
  valid_to_sort_key,
  memory_type,
  visibility_status,
  content,
  summary,
  status
)
SELECT p.id, 'character_memory_node_m3_001', ch.id, tl.id, s.id, e.id, 'T001', 1, 'T001', 1, 'N001', 1, 'T001', 1, 'T999', 999, 'OBJECTIVE_SEEN', 'KNOWN', 'Character knows the M3 smoke fact.', 'Known M3 fact.', 'CONFIRMED'
FROM projects p
JOIN characters ch ON ch.project_id = p.id AND ch.character_id = 'character_m3_001'
JOIN timelines tl ON tl.project_id = p.id AND tl.timeline_id = 'timeline_m3_main'
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m3_001'
JOIN events e ON e.project_id = p.id AND e.event_id = 'event_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, character_memory_node_id) DO UPDATE SET
  summary = EXCLUDED.summary,
  updated_at = now();

INSERT INTO location_state_nodes (
  project_id,
  location_state_node_id,
  location_id,
  timeline_id,
  time_anchor,
  time_anchor_sort_key,
  valid_from,
  valid_from_sort_key,
  valid_to,
  valid_to_sort_key,
  state_snapshot,
  revealed_to_reader_at,
  status
)
SELECT p.id, 'location_state_node_m3_001', wl.id, tl.id, 'T001', 1, 'T001', 1, 'T999', 999, '{"lighting":"dim","door":"closed"}'::jsonb, 'N001', 'CONFIRMED'
FROM projects p
JOIN world_locations wl ON wl.project_id = p.id AND wl.location_id = 'location_m3_001'
JOIN timelines tl ON tl.project_id = p.id AND tl.timeline_id = 'timeline_m3_main'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, location_state_node_id) DO UPDATE SET
  state_snapshot = EXCLUDED.state_snapshot,
  updated_at = now();

INSERT INTO location_change_deltas (
  project_id,
  location_change_delta_id,
  location_id,
  to_node_id,
  source_event_id,
  change_summary,
  change_detail,
  status
)
SELECT p.id, 'location_delta_m3_001', wl.id, lsn.id, e.id, 'M3 state established.', 'The room starts dim with the door closed.', 'CONFIRMED'
FROM projects p
JOIN world_locations wl ON wl.project_id = p.id AND wl.location_id = 'location_m3_001'
JOIN location_state_nodes lsn ON lsn.project_id = p.id AND lsn.location_state_node_id = 'location_state_node_m3_001'
JOIN events e ON e.project_id = p.id AND e.event_id = 'event_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, location_change_delta_id) DO UPDATE SET
  change_summary = EXCLUDED.change_summary,
  updated_at = now();

UPDATE location_state_nodes lsn
SET change_from_previous_id = lcd.id,
    updated_at = now()
FROM projects p
JOIN location_change_deltas lcd ON lcd.project_id = p.id AND lcd.location_change_delta_id = 'location_delta_m3_001'
WHERE lsn.project_id = p.id
  AND p.project_id = 'project_m3_smoke_001'
  AND lsn.location_state_node_id = 'location_state_node_m3_001';

INSERT INTO search_memory_cards (
  project_id,
  search_memory_card_id,
  source_search_document_id,
  timeline_id,
  source_scene_id,
  character_memory_node_id,
  location_state_node_id,
  location_change_delta_id,
  source_type,
  text_summary,
  keywords,
  entity_refs,
  character_refs,
  location_refs,
  world_time_range,
  narrative_range,
  known_by_refs,
  revealed_to_reader_at,
  visibility_status,
  memory_lane,
  status
)
SELECT p.id, 'search_memory_card_m3_001', sd.id, tl.id, s.id, cmn.id, lsn.id, lcd.id, 'character_memory', 'M3 timeline-aware memory card.', '["m3","memory"]'::jsonb, '[{"type":"memory","business_id":"memory_m3_001"}]'::jsonb, '[{"business_id":"character_m3_001"}]'::jsonb, '[{"business_id":"location_m3_001"}]'::jsonb, '{"from":"T001","to":"T999"}'::jsonb, '{"from":"N001","to":"N999"}'::jsonb, '[{"business_id":"character_m3_001"}]'::jsonb, 'N001', 'KNOWN', 'objective', 'CONFIRMED'
FROM projects p
JOIN search_documents sd ON sd.project_id = p.id AND sd.search_document_id = 'search_document_m3_001'
JOIN timelines tl ON tl.project_id = p.id AND tl.timeline_id = 'timeline_m3_main'
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m3_001'
JOIN character_memory_nodes cmn ON cmn.project_id = p.id AND cmn.character_memory_node_id = 'character_memory_node_m3_001'
JOIN location_state_nodes lsn ON lsn.project_id = p.id AND lsn.location_state_node_id = 'location_state_node_m3_001'
JOIN location_change_deltas lcd ON lcd.project_id = p.id AND lcd.location_change_delta_id = 'location_delta_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, search_memory_card_id) DO UPDATE SET
  text_summary = EXCLUDED.text_summary,
  updated_at = now();

INSERT INTO temporal_query_specs (
  project_id,
  temporal_query_id,
  timeline_id,
  scene_id,
  query_type,
  world_time,
  world_time_sort_key,
  narrative_ref,
  narrative_sequence_key,
  knowledge_time,
  knowledge_time_sort_key,
  character_refs,
  location_refs,
  status
)
SELECT p.id, 'temporal_query_m3_001', tl.id, s.id, 'CURRENT_SCENE_GENERATION', 'T001', 1, 'N001', 1, 'T001', 1, '[{"business_id":"character_m3_001"}]'::jsonb, '[{"business_id":"location_m3_001"}]'::jsonb, 'CONFIRMED'
FROM projects p
JOIN timelines tl ON tl.project_id = p.id AND tl.timeline_id = 'timeline_m3_main'
JOIN scenes s ON s.project_id = p.id AND s.scene_id = 'scene_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, temporal_query_id) DO UPDATE SET
  world_time = EXCLUDED.world_time,
  updated_at = now();

INSERT INTO temporal_query_results (
  project_id,
  temporal_query_result_id,
  temporal_query_id,
  search_memory_card_id,
  character_memory_node_id,
  location_state_node_id,
  source_ref,
  access_label,
  validity_reason,
  usable_for_writer,
  temporal_fit,
  status
)
SELECT p.id, 'temporal_query_result_m3_001', tq.id, smc.id, cmn.id, lsn.id, '{"type":"search_memory_card","business_id":"search_memory_card_m3_001"}'::jsonb, 'USABLE_NOW', 'Valid at Tw/Tn/Tk.', true, 1.0000, 'CONFIRMED'
FROM projects p
JOIN temporal_query_specs tq ON tq.project_id = p.id AND tq.temporal_query_id = 'temporal_query_m3_001'
JOIN search_memory_cards smc ON smc.project_id = p.id AND smc.search_memory_card_id = 'search_memory_card_m3_001'
JOIN character_memory_nodes cmn ON cmn.project_id = p.id AND cmn.character_memory_node_id = 'character_memory_node_m3_001'
JOIN location_state_nodes lsn ON lsn.project_id = p.id AND lsn.location_state_node_id = 'location_state_node_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, temporal_query_result_id) DO UPDATE SET
  validity_reason = EXCLUDED.validity_reason,
  updated_at = now();

INSERT INTO query_orchestration_runs (
  project_id,
  query_orchestration_run_id,
  temporal_query_id,
  retrieval_task_id,
  agent_context_pack_id,
  query_mode,
  library_query_id,
  context_pack_id,
  started_at,
  completed_at,
  status
)
SELECT p.id, 'orchestration_run_m3_001', tq.id, rt.id, ap.id, 'CURRENT_SCENE_GENERATION', 'retrieval_task_m3_001', 'agent_pack_m3_001', now(), now(), 'CONFIRMED'
FROM projects p
JOIN temporal_query_specs tq ON tq.project_id = p.id AND tq.temporal_query_id = 'temporal_query_m3_001'
JOIN retrieval_task_specs rt ON rt.project_id = p.id AND rt.retrieval_task_id = 'retrieval_task_m3_001'
JOIN agent_context_packs ap ON ap.project_id = p.id AND ap.agent_context_pack_id = 'agent_pack_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, query_orchestration_run_id) DO UPDATE SET
  completed_at = EXCLUDED.completed_at,
  updated_at = now();

INSERT INTO candidate_fusion_results (
  project_id,
  candidate_fusion_result_id,
  orchestration_run_id,
  search_document_id,
  search_memory_card_id,
  candidate_ref,
  access_label,
  temporal_fit,
  entity_fit,
  semantic_fit,
  authority_score,
  narrative_relevance,
  final_score,
  dedupe_key,
  status
)
SELECT p.id, 'candidate_fusion_m3_allowed', qor.id, sd.id, smc.id, '{"type":"memory","business_id":"memory_m3_001"}'::jsonb, 'USABLE_NOW', 1.0000, 1.0000, 0.9000, 0.9000, 0.8000, 0.9300, 'memory:m3:allowed', 'CONFIRMED'
FROM projects p
JOIN query_orchestration_runs qor ON qor.project_id = p.id AND qor.query_orchestration_run_id = 'orchestration_run_m3_001'
JOIN search_documents sd ON sd.project_id = p.id AND sd.search_document_id = 'search_document_m3_001'
JOIN search_memory_cards smc ON smc.project_id = p.id AND smc.search_memory_card_id = 'search_memory_card_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, candidate_fusion_result_id) DO UPDATE SET
  final_score = EXCLUDED.final_score,
  updated_at = now();

INSERT INTO candidate_fusion_results (
  project_id,
  candidate_fusion_result_id,
  orchestration_run_id,
  candidate_ref,
  access_label,
  final_score,
  dedupe_key,
  status
)
SELECT p.id, 'candidate_fusion_m3_forbidden', qor.id, '{"type":"memory","business_id":"future_secret"}'::jsonb, 'CHARACTER_UNKNOWN', 0.9900, 'memory:m3:forbidden', 'CANDIDATE'
FROM projects p
JOIN query_orchestration_runs qor ON qor.project_id = p.id AND qor.query_orchestration_run_id = 'orchestration_run_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, candidate_fusion_result_id) DO UPDATE SET
  access_label = EXCLUDED.access_label,
  updated_at = now();

INSERT INTO authority_visibility_gate_results (
  project_id,
  authority_visibility_gate_result_id,
  candidate_fusion_id,
  access_label,
  usable_for_writer,
  forbidden_reason,
  authority_reason,
  visibility_reason,
  temporal_reason,
  status
)
SELECT p.id, 'gate_result_m3_allowed', cfr.id, 'USABLE_NOW', true, '', 'confirmed', 'character knows it', 'valid now', 'CONFIRMED'
FROM projects p
JOIN candidate_fusion_results cfr ON cfr.project_id = p.id AND cfr.candidate_fusion_result_id = 'candidate_fusion_m3_allowed'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, authority_visibility_gate_result_id) DO UPDATE SET
  usable_for_writer = EXCLUDED.usable_for_writer,
  updated_at = now();

INSERT INTO authority_visibility_gate_results (
  project_id,
  authority_visibility_gate_result_id,
  candidate_fusion_id,
  access_label,
  usable_for_writer,
  forbidden_reason,
  authority_reason,
  visibility_reason,
  temporal_reason,
  status
)
SELECT p.id, 'gate_result_m3_forbidden', cfr.id, 'CHARACTER_UNKNOWN', false, 'POV character does not know this.', 'candidate', 'character unknown', 'valid later', 'CANDIDATE'
FROM projects p
JOIN candidate_fusion_results cfr ON cfr.project_id = p.id AND cfr.candidate_fusion_result_id = 'candidate_fusion_m3_forbidden'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, authority_visibility_gate_result_id) DO UPDATE SET
  usable_for_writer = EXCLUDED.usable_for_writer,
  updated_at = now();

INSERT INTO context_pack_builds (
  project_id,
  context_pack_build_id,
  orchestration_run_id,
  agent_context_pack_id,
  must_use_refs,
  may_use_refs,
  avoid_revealing_refs,
  character_visible_memory_refs,
  location_current_state_refs,
  continuity_warning_refs,
  source_ref_summary,
  allowed_label_count,
  forbidden_label_count,
  token_estimate,
  status
)
SELECT p.id, 'context_pack_build_m3_001', qor.id, ap.id, '[{"type":"memory","business_id":"memory_m3_001"}]'::jsonb, '[]'::jsonb, '[{"type":"candidate","business_id":"candidate_fusion_m3_forbidden"}]'::jsonb, '[{"type":"character_memory_node","business_id":"character_memory_node_m3_001"}]'::jsonb, '[{"type":"location_state_node","business_id":"location_state_node_m3_001"}]'::jsonb, '[]'::jsonb, '[{"type":"scene","business_id":"scene_m3_001"}]'::jsonb, 1, 1, 80, 'CONFIRMED'
FROM projects p
JOIN query_orchestration_runs qor ON qor.project_id = p.id AND qor.query_orchestration_run_id = 'orchestration_run_m3_001'
JOIN agent_context_packs ap ON ap.project_id = p.id AND ap.agent_context_pack_id = 'agent_pack_m3_001'
WHERE p.project_id = 'project_m3_smoke_001'
ON CONFLICT (project_id, context_pack_build_id) DO UPDATE SET
  allowed_label_count = EXCLUDED.allowed_label_count,
  forbidden_label_count = EXCLUDED.forbidden_label_count,
  updated_at = now();

DO $$
DECLARE
  project_id_value uuid;
  agent_pack_id uuid;
  temporal_query_id_value uuid;
  candidate_fusion_id_value uuid;
  orchestration_run_id_value uuid;
BEGIN
  SELECT id INTO project_id_value
  FROM projects
  WHERE project_id = 'project_m3_smoke_001';

  SELECT id INTO agent_pack_id
  FROM agent_context_packs
  WHERE project_id = project_id_value
    AND agent_context_pack_id = 'agent_pack_m3_001';

  SELECT id INTO temporal_query_id_value
  FROM temporal_query_specs
  WHERE project_id = project_id_value
    AND temporal_query_id = 'temporal_query_m3_001';

  SELECT id INTO candidate_fusion_id_value
  FROM candidate_fusion_results
  WHERE project_id = project_id_value
    AND candidate_fusion_result_id = 'candidate_fusion_m3_forbidden';

  SELECT id INTO orchestration_run_id_value
  FROM query_orchestration_runs
  WHERE project_id = project_id_value
    AND query_orchestration_run_id = 'orchestration_run_m3_001';

  BEGIN
    INSERT INTO pack_items (
      project_id,
      pack_item_id,
      agent_context_pack_id,
      pack_type,
      entity_type,
      entity_business_id,
      access_label,
      included_in_writer_context,
      status
    ) VALUES (
      project_id_value,
      'pack_item_m3_forbidden_writer_check',
      agent_pack_id,
      'AGENT',
      'memory',
      'future_secret',
      'CHARACTER_UNKNOWN',
      true,
      'CANDIDATE'
    );

    RAISE EXCEPTION 'Expected forbidden pack item writer inclusion CHECK rejection';
  EXCEPTION
    WHEN check_violation THEN
      NULL;
  END;

  BEGIN
    INSERT INTO temporal_query_results (
      project_id,
      temporal_query_result_id,
      temporal_query_id,
      access_label,
      usable_for_writer,
      validity_reason,
      status
    ) VALUES (
      project_id_value,
      'temporal_query_result_m3_forbidden_writer_check',
      temporal_query_id_value,
      'CHARACTER_UNKNOWN',
      true,
      'This should be rejected by writer allowlist.',
      'CANDIDATE'
    );

    RAISE EXCEPTION 'Expected forbidden temporal result writer usability CHECK rejection';
  EXCEPTION
    WHEN check_violation THEN
      NULL;
  END;

  BEGIN
    INSERT INTO authority_visibility_gate_results (
      project_id,
      authority_visibility_gate_result_id,
      candidate_fusion_id,
      access_label,
      usable_for_writer,
      forbidden_reason,
      status
    ) VALUES (
      project_id_value,
      'gate_result_m3_forbidden_writer_check',
      candidate_fusion_id_value,
      'CHARACTER_UNKNOWN',
      true,
      'This should be rejected by writer allowlist.',
      'CANDIDATE'
    );

    RAISE EXCEPTION 'Expected forbidden gate writer usability CHECK rejection';
  EXCEPTION
    WHEN check_violation THEN
      NULL;
  END;

  BEGIN
    INSERT INTO candidate_fusion_results (
      project_id,
      candidate_fusion_result_id,
      orchestration_run_id,
      candidate_ref,
      access_label,
      final_score,
      dedupe_key,
      status
    ) VALUES (
      project_id_value,
      'candidate_fusion_m3_duplicate_dedupe',
      orchestration_run_id_value,
      '{"type":"memory","business_id":"memory_m3_001_duplicate"}'::jsonb,
      'USABLE_NOW',
      0.5000,
      'memory:m3:allowed',
      'CANDIDATE'
    );

    RAISE EXCEPTION 'Expected duplicate candidate fusion dedupe_key rejection';
  EXCEPTION
    WHEN unique_violation THEN
      NULL;
  END;
END $$;

UPDATE scene_memory_packs sp
SET freshness_status = 'STALE',
    invalidated_at = now(),
    invalidated_reason = 'M3 smoke dependency changed',
    updated_at = now()
FROM projects p
WHERE sp.project_id = p.id
  AND p.project_id = 'project_m3_smoke_001'
  AND sp.scene_memory_pack_id = 'scene_pack_m3_001';

DO $$
DECLARE
  scene_pack_rows integer;
  stale_pack_rows integer;
  current_location_rows integer;
  visible_character_memory_rows integer;
  forbidden_gate_rows integer;
  forbidden_writer_pack_items integer;
BEGIN
  SELECT count(*) INTO scene_pack_rows
  FROM scene_memory_packs sp
  JOIN agent_context_packs ap ON ap.scene_pack_id = sp.id AND ap.project_id = sp.project_id
  JOIN pack_items pi ON pi.agent_context_pack_id = ap.id AND pi.project_id = ap.project_id
  JOIN projects p ON p.id = sp.project_id
  WHERE p.project_id = 'project_m3_smoke_001'
    AND sp.scene_memory_pack_id = 'scene_pack_m3_001'
    AND pi.access_label = 'USABLE_NOW';

  IF scene_pack_rows <> 1 THEN
    RAISE EXCEPTION 'Expected scene pack structured path row, got %', scene_pack_rows;
  END IF;

  SELECT count(*) INTO stale_pack_rows
  FROM scene_memory_packs sp
  JOIN projects p ON p.id = sp.project_id
  WHERE p.project_id = 'project_m3_smoke_001'
    AND sp.scene_memory_pack_id = 'scene_pack_m3_001'
    AND sp.freshness_status = 'STALE'
    AND sp.invalidated_at IS NOT NULL;

  IF stale_pack_rows <> 1 THEN
    RAISE EXCEPTION 'Expected one stale scene pack after freshness invalidation, got %', stale_pack_rows;
  END IF;

  SELECT count(*) INTO current_location_rows
  FROM location_state_nodes lsn
  JOIN projects p ON p.id = lsn.project_id
  WHERE p.project_id = 'project_m3_smoke_001'
    AND lsn.time_anchor_sort_key <= 1
    AND lsn.valid_from_sort_key <= 1
    AND (lsn.valid_to_sort_key IS NULL OR lsn.valid_to_sort_key > 1)
    AND lsn.superseded_by_id IS NULL;

  IF current_location_rows <> 1 THEN
    RAISE EXCEPTION 'Expected current location state lookup row, got %', current_location_rows;
  END IF;

  SELECT count(*) INTO visible_character_memory_rows
  FROM character_memory_nodes cmn
  JOIN projects p ON p.id = cmn.project_id
  WHERE p.project_id = 'project_m3_smoke_001'
    AND cmn.known_at_sort_key <= 1
    AND cmn.valid_from_sort_key <= 1
    AND (cmn.valid_to_sort_key IS NULL OR cmn.valid_to_sort_key > 1)
    AND cmn.visibility_status IN ('KNOWN', 'RESTORED')
    AND cmn.superseded_by_id IS NULL;

  IF visible_character_memory_rows <> 1 THEN
    RAISE EXCEPTION 'Expected visible character memory row, got %', visible_character_memory_rows;
  END IF;

  SELECT count(*) INTO forbidden_gate_rows
  FROM authority_visibility_gate_results avgr
  JOIN projects p ON p.id = avgr.project_id
  WHERE p.project_id = 'project_m3_smoke_001'
    AND avgr.access_label = 'CHARACTER_UNKNOWN'
    AND avgr.usable_for_writer = false;

  IF forbidden_gate_rows <> 1 THEN
    RAISE EXCEPTION 'Expected one forbidden gate label row, got %', forbidden_gate_rows;
  END IF;

  SELECT count(*) INTO forbidden_writer_pack_items
  FROM pack_items pi
  JOIN projects p ON p.id = pi.project_id
  WHERE p.project_id = 'project_m3_smoke_001'
    AND pi.included_in_writer_context = true
    AND pi.access_label <> 'USABLE_NOW';

  IF forbidden_writer_pack_items <> 0 THEN
    RAISE EXCEPTION 'Expected WriterAgent context pack to exclude forbidden labels, got % forbidden items', forbidden_writer_pack_items;
  END IF;
END $$;

DO $$
DECLARE
  project_a uuid;
  project_b uuid;
  cross_scene_id uuid;
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
      'project_m3_cross_a',
      'M3 Cross Project A',
      'zh',
      'POSTGRES_SHADOW',
      'DRAFT',
      'm3_cross',
      'ACTIVE',
      'USER_CONFIRMED',
      'm3:cross:a',
      'SYSTEM'
    ),
    (
      'project_m3_cross_b',
      'M3 Cross Project B',
      'zh',
      'POSTGRES_SHADOW',
      'DRAFT',
      'm3_cross',
      'ACTIVE',
      'USER_CONFIRMED',
      'm3:cross:b',
      'SYSTEM'
    )
  ON CONFLICT (project_id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    updated_at = now();

  SELECT id INTO project_a FROM projects WHERE project_id = 'project_m3_cross_a';
  SELECT id INTO project_b FROM projects WHERE project_id = 'project_m3_cross_b';

  INSERT INTO chapters (project_id, chapter_id, chapter_number, title, status)
  VALUES (project_a, 'chapter_m3_cross_a', 390, 'M3 Cross Chapter A', 'DRAFT')
  ON CONFLICT (project_id, chapter_id) DO UPDATE SET
    title = EXCLUDED.title,
    updated_at = now();

  INSERT INTO scenes (project_id, scene_id, chapter_id, scene_order, scene_title, status)
  SELECT project_a, 'scene_m3_cross_a', c.id, 1, 'M3 Cross Scene A', 'DRAFT'
  FROM chapters c
  WHERE c.project_id = project_a
    AND c.chapter_id = 'chapter_m3_cross_a'
  ON CONFLICT (project_id, scene_id) DO UPDATE SET
    scene_title = EXCLUDED.scene_title,
    updated_at = now();

  SELECT id INTO cross_scene_id
  FROM scenes
  WHERE project_id = project_a
    AND scene_id = 'scene_m3_cross_a';

  BEGIN
    INSERT INTO scene_memory_packs (
      project_id,
      scene_memory_pack_id,
      scene_id,
      pack_purpose,
      freshness_status,
      status
    ) VALUES (
      project_b,
      'scene_pack_m3_cross_forbidden',
      cross_scene_id,
      'forbidden cross-project pack',
      'FRESH',
      'DRAFT'
    );

    RAISE EXCEPTION 'Expected cross-project M3 scene_memory_packs FK rejection';
  EXCEPTION
    WHEN foreign_key_violation THEN
      NULL;
  END;
END $$;

ROLLBACK;
