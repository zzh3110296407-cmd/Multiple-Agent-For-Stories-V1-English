# Framework Library UI V1

Date: 2026-07-03

## Position

Framework Library is a branch inside Framework Composition. It stores reusable framework materials, patterns, and composition rules. It does not write current story facts by itself.

Primary purpose:

- Review reusable assets created from confirmed imports, Analyze Stories derivations, selected candidates, user-created sources, or system defaults.
- Filter by item type, source type, visibility, maturity, and copyright risk.
- Review candidate composition rules.
- Archive unsafe/unneeded items.
- Build private framework collections for later use in Framework Composition.

## Visual Direction

- Palette: classic parchment Morandi with muted terracotta, gray-blue, and catalog-card ivory.
- Mood: archive room, card catalog, reusable story machinery.
- Background: faint shelves, index cards, and catalog shadows. This separates the Library from the analyzer page while staying in the same story UI family.
- Layout: left source/filter rail, center material catalog, right review/collection rail, bottom-right action dock.

## Page Structure

1. Top bar
   - Back to Framework.
   - Breadcrumb: Home / Current Project / Framework / Framework Library.
   - Compact refresh/ledger entry.

2. Header
   - Title: Framework Library.
   - Summary metrics:
     - Items.
     - Patterns.
     - Rules.
     - Private collections.
     - Risk flags.

3. Left: Source and Filters
   - Build sources:
     - Confirmed import.
     - Adapter derivation.
     - Selected candidates.
   - Filter controls:
     - Item type.
     - Source type.
     - Visibility.
     - Risk.
   - Notes field for safe user note.

4. Center: Catalog
   - Tabs:
     - Items.
     - Patterns.
     - Rules.
     - Private.
   - Search field.
   - Material cards show label, summary, type, source, visibility, maturity, risk, and confirmation requirement.
   - Selecting a card updates the right panel.

5. Right: Review and Collection
   - Selected asset detail.
   - Source and risk summary.
   - Rule review area:
     - Mark reviewed.
     - Reject rule.
   - Private framework composer:
     - Collection title.
     - Included items/patterns/rules preview.

6. Bottom-right action dock
   - Refresh.
   - Archive selected.
   - Create private framework.

## Required Interactions

- Source cards switch selected build source.
- Filter chips switch selected filter state.
- Catalog tabs switch visible catalog type.
- Clicking a catalog card updates the selected detail panel.
- Rule review and private framework buttons show pending/success states.

## API Contract Mapping

Build into Library:

- `POST /api/framework-library/items/from-confirmed-import`
  - Request: `imported_framework_decision_id`, `safe_user_note`.
- `POST /api/framework-library/items/from-adapter-derivation`
  - Request: `derivation_report_id`, `safe_user_note`.
- `POST /api/framework-library/items/from-selected-candidates`
  - Request: `candidate_ids`, `safe_user_note`.
- `POST /api/framework-library/items/from-vocabulary-artifact`
  - Request: `artifact`, `source_ref`, `safe_user_note`.
  - Backend exists; current frontend wrapper does not yet expose this endpoint.

Library records:

- `GET /api/framework-library/items`
  - Query: `item_type`, `source_type`, `visibility`, `maturity_level`, `risk_level`.
- `GET /api/framework-library/items/{library_item_id}`
- `PATCH /api/framework-library/items/{library_item_id}`
  - Request: `visibility`, `safe_user_note`.
- `POST /api/framework-library/items/{library_item_id}/archive`
  - Request: `safe_user_note`.

Patterns and rules:

- `GET /api/framework-library/patterns`
  - Query: `pattern_type`, `source_type`.
- `GET /api/framework-library/patterns/{pattern_id}`
- `GET /api/framework-library/composition-rules`
  - Query: `status`.
- `GET /api/framework-library/composition-rules/{rule_id}`
- `POST /api/framework-library/composition-rules/{rule_id}/mark-reviewed`
  - Request: `safe_user_note`.
- `POST /api/framework-library/composition-rules/{rule_id}/reject`
  - Request: `safe_user_note`.

Risk, maturity, collections:

- `GET /api/framework-library/maturity-records`
- `GET /api/framework-library/copyright-sources`
  - Query: `risk_level`.
- `POST /api/framework-library/private-frameworks`
  - Request: `title`, `item_ids`, `pattern_ids`, `composition_rule_ids`, `safe_user_note`.
- `GET /api/framework-library/private-frameworks`
- `GET /api/framework-library/system-recommendations`

Important model fields:

- `FrameworkModuleLibraryItem`
  - `library_item_id`
  - `item_type`
  - `source_type`
  - `label`
  - `safe_summary`
  - `source_refs`
  - `visibility`
  - `constraint_strength`
  - `maturity_record_id`
  - `copyright_source_record_id`
  - `requires_user_confirmation`
  - `warnings`
- `FrameworkPatternRecord`
  - `pattern_id`
  - `pattern_type`
  - `source_type`
  - `label`
  - `safe_summary`
  - `visibility`
  - `requires_user_confirmation`
- `ModuleCompositionRule`
  - `rule_id`
  - `relation_type`
  - `rule_status`
  - `source_pattern_ids`
  - `target_pattern_ids`
  - `safe_summary`
  - `requires_user_confirmation`
- `CopyrightSourceRecord`
  - `risk_level`
  - `visibility_limit`
  - `examples_stripped`
  - `authority_downgraded`
  - `warnings`
- `FrameworkMaturityRecord`
  - `maturity_level`
  - `requires_user_confirmation`
  - `warning_count`
  - `blocking_issue_count`
- `UserPrivateFramework`
  - `private_framework_id`
  - `title`
  - `item_ids`
  - `pattern_ids`
  - `composition_rule_ids`
  - `visibility`

## Implementation Notes For Codes

- Library materials are reusable references, not current story facts.
- Composition rules are suggestions until a later workflow explicitly applies them.
- Apparent contradiction templates are not continuity-error waivers.
- Show high/blocked copyright risk before allowing project-local promotion.
- HTTP 409 build results should show the blocked build report instead of a broken page.
- Keep raw IDs available in detail views/tooltips, but primary labels should use readable names and summaries.

## Visual Draft

- `visual-drafts/framework-library-v1.html`
- `visual-drafts/framework-library-v1.png`
