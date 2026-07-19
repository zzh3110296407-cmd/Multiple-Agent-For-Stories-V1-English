# Analyze Stories UI V1

Date: 2026-07-03

## Position

Analyze Stories is a Framework branch. The user enters it only from Framework Composition when choosing the analyzer/import path. It is not a separate main product step.

Primary purpose:

- Import an existing story/analyzer artifact.
- Run safe parsing and validation.
- Review report/bundle/candidate results.
- Send a confirmed Framework candidate back to Framework Composition.

## Visual Direction

- Palette: parchment Morandi base, aged ivory panels, muted dragon-leather terracotta accent, soft blue-gray analyzer details.
- Mood: manuscript desk, archival lens, quiet investigation.
- Layout: three-column work surface plus bottom-right action dock.
- Background: faint manuscript sheets, ink paths, magnifier ring, no dragon background. This distinguishes it from Home and Framework while staying in the same story-world UI system.

## Page Structure

1. Top bar
   - Back to Framework.
   - Breadcrumb: Home / Current Project / Framework / Analyze Stories.
   - Compact import ledger entry.

2. Left: Import Story
   - Drop zone / paste zone.
   - File kind selector:
     - Auto detect.
     - Full book bundle.
     - Story analysis report.
     - Framework package.
     - Cross-chapter state.
   - Current import summary.
   - Safety status: raw storage, redaction/hash, parse status.

3. Center: Analysis Pipeline
   - Import gate.
   - Bundle validation.
   - Report viewer.
   - Adapter candidates.
   - Framework candidate.
   - Selected step detail changes when clicked.
   - Report preview and chapter inventory preview.

4. Right: Candidate Handoff
   - Framework candidate card.
   - Adapter candidate families:
     - Chapter archive.
     - Narrative debt.
     - Open thread.
     - Closed thread.
     - Payoff.
     - Apparent contradiction.
   - Activation mode:
     - Reference only.
     - Merge.
     - Set active.
   - Handoff checks.

5. Bottom-right action dock
   - Revalidate.
   - Generate candidates.
   - Send to Framework.

## Required Interactions

- File-kind chips update the import type state.
- Pipeline step click updates the center detail card.
- Candidate family chips filter/highlight candidate preview.
- Activation mode buttons switch handoff intent.
- Primary action buttons show pending/success/error states during API calls.

## API Contract Mapping

Import gate:

- `POST /api/analyze-stories/imports`
  - Request fields: `declared_file_kind`, `original_filename`, `artifact`.
  - UI state source: `AnalyzeStoriesImportResult`.
- `GET /api/analyze-stories/imports`
- `GET /api/analyze-stories/imports/{import_id}`
- `POST /api/analyze-stories/imports/{import_id}/revalidate`

Important import fields:

- `manifest.import_status`
- `manifest.parse_status`
- `manifest.file_kinds`
- `artifact.file_kind`
- `artifact.raw_storage_status`
- `validation_report.passed`
- `validation_report.can_proceed_to_m2`
- `validation_report.blocking_issues`
- `validation_report.warnings`
- `story_analysis_report_refs`

Bundle validation:

- `POST /api/analyze-stories/imports/{import_id}/bundle-validation`
- `GET /api/analyze-stories/bundles`
- `GET /api/analyze-stories/bundles/{bundle_manifest_id}`
- `GET /api/analyze-stories/bundles/{bundle_manifest_id}/validation-report`
- `GET /api/analyze-stories/bundles/{bundle_manifest_id}/chapter-inventory`
- `GET /api/analyze-stories/bundles/{bundle_manifest_id}/cross-chapter-ref-checks`
- `POST /api/analyze-stories/bundles/{bundle_manifest_id}/revalidate`

Important bundle fields:

- `manifest.bundle_status`
- `manifest.reliability_level`
- `manifest.detected_chapter_count`
- `manifest.can_be_used_as_reference`
- `manifest.can_proceed_to_m6_adapter`
- `chapter_inventory.entries`
- `validation_report.blocking_issues`
- `validation_report.warnings`

Report viewer:

- `POST /api/analyze-stories/report-viewers`
- `GET /api/analyze-stories/reports/{report_ref_id}/viewer-state`
- `GET /api/analyze-stories/report-viewers`
- `GET /api/analyze-stories/report-viewers/{viewer_state_id}`
- `POST /api/analyze-stories/report-viewers/{viewer_state_id}/mark-reviewed`
- `POST /api/analyze-stories/report-viewers/{viewer_state_id}/flag`
- `POST /api/analyze-stories/report-viewers/{viewer_state_id}/dismiss`

Important viewer fields:

- `viewer_state.viewer_status`
- `viewer_state.review_status`
- `viewer_state.safe_title`
- `viewer_state.safe_summary`
- `section_views`
- `reference_links`
- `warning_count`
- `blocking_issue_count`

Adapter candidates:

- `POST /api/analyze-stories/bundles/{bundle_manifest_id}/adapter-derivations`
- `GET /api/analyze-stories/adapter-derivations`
- `GET /api/analyze-stories/adapter-derivations/{derivation_report_id}`
- `GET /api/analyze-stories/adapter-candidates`
- `GET /api/analyze-stories/adapter-candidates/{candidate_id}`
- `POST /api/analyze-stories/adapter-candidates/{candidate_id}/mark-reviewed`
- `POST /api/analyze-stories/adapter-candidates/{candidate_id}/defer`
- `POST /api/analyze-stories/adapter-candidates/{candidate_id}/reject`

Important adapter fields:

- `derivation_report.derivation_status`
- `derivation_report.reliability_level`
- `derivation_report.can_be_used_as_reference`
- `derivation_report.can_proceed_to_m6_adapter`
- `candidate.candidate_family`
- `candidate.candidate_status`
- `candidate.safe_summary`
- `candidate.warnings`
- `candidate.blocking_issues`

Framework candidate and imported Framework workbench:

- `POST /api/analyze-stories/imports/{import_id}/framework-candidates`
- `GET /api/analyze-stories/framework-candidates`
- `GET /api/analyze-stories/framework-candidates/{candidate_id}`
- `POST /api/analyze-stories/framework-candidates/{candidate_id}/revalidate`
- `GET /api/analyze-stories/framework-candidates/{candidate_id}/imported-workbench`
- `POST /api/analyze-stories/framework-candidates/{candidate_id}/edit-sessions`
- `PATCH /api/analyze-stories/imported-framework-edit-sessions/{edit_session_id}`
- `POST /api/analyze-stories/imported-framework-edit-sessions/{edit_session_id}/validate`
- `POST /api/analyze-stories/imported-framework-edit-sessions/{edit_session_id}/activation-plan`
- `POST /api/analyze-stories/imported-framework-activation-plans/{plan_id}/confirm`
- `POST /api/analyze-stories/imported-framework-edit-sessions/{edit_session_id}/reject`

Important workbench fields:

- `candidate.candidate_status`
- `candidate.can_proceed_to_m4_workbench`
- `candidate.requires_user_confirmation`
- `edit_session.session_status`
- `edit_session.activation_mode`
- `edit_session.warning_count`
- `edit_session.blocking_issue_count`
- `activation_plan.impact_summary`
- `activation_plan.accept_warnings_required`

## Implementation Notes For Codes

- Do not write imported content into active Framework until the user confirms an activation plan.
- Story analysis reports are human-readable reference material; they do not activate generation constraints by themselves.
- Surface warnings and blocking issues as user-facing status, but keep raw hashes and internal IDs in detail drawers or debug-only areas.
- Keep `declared_file_kind` optional because the backend supports auto-detection.
- The UI should treat HTTP 409 from adapter derivation as a valid blocked result, not as a broken page.

## Visual Draft

- `visual-drafts/analyze-stories-v1.html`
- `visual-drafts/analyze-stories-v1.png`
