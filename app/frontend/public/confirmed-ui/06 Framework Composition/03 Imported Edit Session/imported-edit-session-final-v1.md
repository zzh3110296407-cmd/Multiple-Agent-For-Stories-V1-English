# Imported Edit Session UI V1

Date: 2026-07-03

## Position

Imported Edit Session is the editing and confirmation branch for an Analyze Stories Framework candidate. It opens an inactive working copy of an imported Framework candidate, lets the user adjust it, validates the copy, builds an activation plan, and only then lets the user confirm or reject it.

This page belongs under Framework Composition / Analyze Stories import flow. It is not a normal story-writing workspace.

## Visual Direction

- Palette: parchment Morandi base with muted terracotta, ink-gray, blue-gray review markers.
- Mood: editorial desk, layered blueprint, import mapping board.
- Layout: three-column workbench:
  - Candidate/session rail.
  - Imported framework editor.
  - Validation and activation plan rail.
- Background: faint blueprint sheets and thread-map arcs, suggesting careful structural migration rather than creative generation.

## Page Structure

1. Top bar
   - Back to Framework.
   - Breadcrumb: Home / Current Project / Framework / Imported Edit Session.
   - Session ledger button.

2. Header
   - Title: 导入编辑会话.
   - Summary metrics:
     - Session status.
     - Activation mode.
     - Patches.
     - Warnings.
     - Blocking issues.

3. Left: Candidate and Session Rail
   - Selected M4-ready candidate.
   - Start/open edit session.
   - Session ledger:
     - draft.
     - validated.
     - plan_ready.
   - Source references:
     - framework candidate.
     - story analysis report viewer.
     - import artifact.

4. Center: Imported Framework Editor
   - Current vs imported comparison.
   - Activation mode segmented control:
     - 仅参考: reference_only.
     - 合并: merge.
     - 设为当前: set_active.
   - Macro component editor:
     - component list.
     - label.
     - instruction.
     - order.
     - delete/restore.
   - Chapter mapping:
     - chapter count.
     - selected chapter.
     - linked macro components.

5. Right: Validation and Activation Plan
   - Validation report:
     - passed.
     - warning count.
     - blocking issue count.
     - requires user confirmation.
   - Impact summary:
     - will write framework package.
     - will write import decision.
     - will write macro mapping decision.
     - will rebuild built chapter frameworks.
   - Confirmation note.

6. Bottom-right action dock
   - Save edit.
   - Validate.
   - Generate plan.
   - Confirm plan.

## Required Interactions

- Selecting session updates status and selected detail.
- Activation mode switch updates visible impact summary.
- Selecting macro component updates the edit form.
- Selecting chapter updates linked macro IDs.
- Action dock shows pending/success/error states.

## API Contract Mapping

Workbench state:

- `GET /api/analyze-stories/framework-candidates/{candidate_id}/imported-workbench`
  - Returns `ImportedFrameworkWorkbenchState`.
  - Important fields:
    - `candidate_id`
    - `candidate_status`
    - `can_start_edit_session`
    - `latest_edit_session_id`
    - `candidate_summary`
    - `current_framework_summary`
    - `source_refs`
    - `viewer_state_ids`
    - `sessions`
    - `warnings`
    - `blocking_issues`
    - `safe_notice`

Start/open session:

- `POST /api/analyze-stories/framework-candidates/{candidate_id}/edit-sessions`
  - Returns `ImportedFrameworkSessionResult`.
- `GET /api/analyze-stories/imported-framework-edit-sessions`
  - Returns `ImportedFrameworkListResponse`.
- `GET /api/analyze-stories/imported-framework-edit-sessions/{edit_session_id}`
  - Returns `ImportedFrameworkSessionResult`.

Patch session:

- `PATCH /api/analyze-stories/imported-framework-edit-sessions/{edit_session_id}`
  - Request fields:
    - `operation`
    - `activation_mode`
    - `component_id`
    - `chapter_index`
    - `patch`
    - `linked_macro_component_ids`
    - `chapter_count`
    - `user_input`
    - `accept_warnings`
  - Supported `operation` values:
    - `set_activation_mode`
    - `update_macro_component`
    - `delete_macro_component`
    - `restore_macro_component`
    - `reorder_macro_components`
    - `remap_chapter`
    - `update_chapter_count`

Validate and activate:

- `POST /api/analyze-stories/imported-framework-edit-sessions/{edit_session_id}/validate`
  - Returns `ImportedFrameworkSessionResult`.
- `POST /api/analyze-stories/imported-framework-edit-sessions/{edit_session_id}/activation-plan`
  - Request: `activation_mode`.
  - Returns `ImportedFrameworkPlanResult`.
- `POST /api/analyze-stories/imported-framework-activation-plans/{plan_id}/confirm`
  - Request: `user_input`, `accept_warnings`.
  - Returns `ImportedFrameworkDecisionResult`.
- `POST /api/analyze-stories/imported-framework-edit-sessions/{edit_session_id}/reject`
  - Request: `user_input`.
  - Returns `ImportedFrameworkDecisionResult`.

Important session fields:

- `edit_session_id`
- `candidate_id`
- `session_status`
- `activation_mode`
- `working_framework_package`
- `original_candidate_summary`
- `source_refs`
- `patch_ids`
- `latest_validation_report`
- `latest_activation_plan_id`
- `warning_count`
- `blocking_issue_count`
- `safe_notice`

Important activation fields:

- `plan_id`
- `plan_status`
- `activation_mode`
- `validation_report`
- `impact_summary`
- `accept_warnings_required`
- `warning_count`
- `blocking_issue_count`

Important impact fields:

- `will_write_framework_package`
- `will_write_import_decision`
- `will_write_framework_macro_mapping_decision`
- `will_rebuild_built_chapter_frameworks`
- `built_chapter_frameworks_stale_warning_count`
- `untouched_files`
- `warnings`
- `safe_summary`

## Implementation Notes For Codes

- Imported Framework sessions are inactive working copies until a plan is confirmed.
- The UI must not imply that report prose becomes generation constraints.
- `reference_only` should read as audit/reference only.
- `merge` and `set_active` require explicit activation plan confirmation.
- If `accept_warnings_required` is true, the confirm button needs an accept warnings control.
- Blocking issues should disable confirm and surface the blocking detail.
- Patch operations should be optimistic only if rollback/error display is available.

## Visual Draft

- `visual-drafts/imported-edit-session-v1.html`
- `visual-drafts/imported-edit-session-v1.png`
