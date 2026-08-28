[CmdletBinding()]
param(
    [int]$Limit = 0,
    [switch]$Stale
)

$ErrorActionPreference = 'Stop'

$argsList = @()
if ($Limit -gt 0) { $argsList += "--limit", "$Limit" }
if ($Stale) { $argsList += "--stale" }

& uv run --package episignal-backend python -m episignal_backend.event_runner @argsList
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
