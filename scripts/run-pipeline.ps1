[CmdletBinding()]
param(
    [ValidateSet('ingest_who', 'ingest_ecdc', 'discover', 'dedupe', 'extract', 'geocode', 'match')]
    [string]$Only
)

$ErrorActionPreference = 'Stop'

$argsList = @("--trigger", "scheduled")
if ($Only) { $argsList += "--only", $Only }

& uv run --package episignal-backend python -m episignal_backend.pipeline_runner @argsList
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
