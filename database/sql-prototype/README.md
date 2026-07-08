# SQL Prototype

This folder contains Database-session SQL/psql prototypes only.

Rules:

- Do not import these files from the main backend.
- Do not add Python PostgreSQL dependencies for M0/M1.
- Use `psql` for local smoke validation.
- Keep prototype objects in schema `mas_phase875_proto`.

Suggested local commands:

```powershell
$checksum = (Get-FileHash .\migrations\001_foundation_projects.sql -Algorithm SHA256).Hash.ToLower()
psql -w -X -v ON_ERROR_STOP=1 -v migration_checksum_sha256=$checksum "$env:DATABASE_URL" -f .\migrations\001_foundation_projects.sql
psql -w -X -v ON_ERROR_STOP=1 "$env:DATABASE_URL" -f .\verify\001_foundation_projects_smoke.sql
```

M2 static schema prototype order:

```powershell
$files = @(
  "001_foundation_projects.sql",
  "002_model_setup_story_intent.sql",
  "003_world_character_framework.sql",
  "004_chapters_scenes_drafts.sql",
  "005_events_state_decisions_gates.sql",
  "006_memory_foundation.sql",
  "007_memory_links_packs.sql",
  "008_quality_subjective_governance.sql"
)

foreach ($file in $files) {
  $checksum = (Get-FileHash ".\migrations\$file" -Algorithm SHA256).Hash.ToLower()
  psql -w -X -v ON_ERROR_STOP=1 -v migration_checksum_sha256=$checksum "$env:DATABASE_URL" -f ".\migrations\$file"
}

psql -w -X -v ON_ERROR_STOP=1 "$env:DATABASE_URL" -f .\verify\m2_schema_smoke.sql
psql -w -X -v ON_ERROR_STOP=1 "$env:DATABASE_URL" -f .\verify\m2b_schema_smoke.sql
```

`m2_schema_smoke.sql` and `m2b_schema_smoke.sql` include negative cross-project FK checks that should raise and catch `foreign_key_violation`.

M3 retrieval/timeline prototype order:

```powershell
$files = @(
  "009_library_retrieval_foundation.sql",
  "010_timeline_memory_state_query.sql"
)

foreach ($file in $files) {
  $checksum = (Get-FileHash ".\migrations\$file" -Algorithm SHA256).Hash.ToLower()
  psql -w -X -v ON_ERROR_STOP=1 -v migration_checksum_sha256=$checksum "$env:DATABASE_URL" -f ".\migrations\$file"
}

psql -w -X -v ON_ERROR_STOP=1 "$env:DATABASE_URL" -f .\verify\m3_retrieval_timeline_smoke.sql
```

`m3_retrieval_timeline_smoke.sql` includes checks for structured scene pack construction, pack freshness invalidation, location state lookup by time, character memory visibility filtering, WriterAgent forbidden-label exclusion and a negative cross-project FK path.

Secure local M3 live validation runner:

```powershell
.\run_m3_live_validation.ps1 -HostName 127.0.0.1 -Port 5432 -UserName postgres -DatabaseName postgres
```

The runner prompts for the PostgreSQL password with `Read-Host -AsSecureString`, sets `PGPASSWORD` only for the script process, clears it in `finally`, applies migrations `001` through `010`, and runs:

- `001_foundation_projects_smoke.sql`
- `m2_schema_smoke.sql`
- `m2b_schema_smoke.sql`
- `m3_retrieval_timeline_smoke.sql`

It writes sanitized output to `..\06-validation\m3-live-validation-output-2026-07-04.log` and status JSON to `..\06-validation\m3-live-validation-status-2026-07-04.json`.

If the same PowerShell process already has `PGPASSWORD` set, use:

```powershell
.\run_m3_live_validation.ps1 -HostName 127.0.0.1 -Port 5432 -UserName postgres -DatabaseName postgres -UseExistingPGPassword
```

Authentication entered into a separate PowerShell window, or into a previous `psql` password prompt, is not a reusable credential for a different Codex subprocess. Do not paste password-bearing connection strings into validation reports or command logs. Without a password, peer/trust auth rule, `pgpass.conf`, or inherited `PGPASSWORD` in the process running the script, live validation remains blocked.
