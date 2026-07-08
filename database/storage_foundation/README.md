# Storage Foundation Prototype

This package is the Phase 8.75 M1 storage boundary prototype for the Database session only.

It is not imported by the main backend runtime and it does not add PostgreSQL Python dependencies. The PostgreSQL skeleton uses `psql` subprocess commands so M0/M1 can validate SQL contracts before any approved backend integration.

## Files

- `contracts.py` defines repository, pack, migration and storage-port protocols.
- `storage_modes.py` defines canonical storage modes plus status/lifecycle/authority enums.
- `entity_refs.py` defines project-scoped business entity references and source references.
- `adapters/postgres_adapter.py` builds non-interactive `psql` commands for connection checks, migration application and smoke SQL.
- `tests/test_storage_foundation_contracts.py` guards the M1 contract vocabulary and adapter command construction.

## Secret Handling

`PsqlPostgresAdapter` may execute a raw password-bearing connection URI, but diagnostic commands exposed by `command_for_sql`, `command_for_file` and `PsqlExecutionResult.command` redact URI passwords as `***`. `PsqlExecutionResult.stdout` and `PsqlExecutionResult.stderr` also replace the configured raw connection URI with its redacted form if it appears in process output.

## Boundary

Main backend files, runtime storage switching and Python PostgreSQL dependencies remain out of scope until separately approved.
