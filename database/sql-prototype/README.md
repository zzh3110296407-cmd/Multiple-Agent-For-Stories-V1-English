# PostgreSQL Schema And Validation

This directory contains the PostgreSQL schema used by the optional
`postgres_primary` storage mode.

The default Docker configuration uses `json_primary`; users who keep that
default do not need to apply these migrations.

## Layout

- `migrations/` contains the ordered schema migrations.
- `verify/` contains optional smoke checks for the migrated schema.

## Applying Migrations

Apply every file in `migrations/` in filename order. Both files whose names
begin with `017_` are required.

Each migration records its checksum. When using `psql`, provide the lowercase
SHA-256 checksum through `migration_checksum_sha256`:

```powershell
$files = Get-ChildItem .\migrations\*.sql | Sort-Object Name
foreach ($file in $files) {
  $checksum = (Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLower()
  psql -w -X -v ON_ERROR_STOP=1 `
    -v migration_checksum_sha256=$checksum `
    "$env:DATABASE_URL" `
    -f $file.FullName
}
```

Set `DATABASE_URL` locally before running the command. Do not place a
password-bearing connection string in a committed file or terminal log.

After migration, the scripts in `verify/` can be run with `psql` to validate
the corresponding schema areas. The smoke scripts write test data inside
transactions and roll back where applicable; review each script before using
it against a non-development database.
