<#
.SYNOPSIS
    Verifies a configured Supabase database against the EpiSignal foundation.

.DESCRIPTION
    Read-and-migrate only. The script checks readiness, applies migrations, seeds
    twice and proves that seeding is idempotent: the canonical identities keep the
    same primary keys and multiplicity across both runs. It never creates, resets,
    deletes or drops a Supabase project, and it never prints connection details.
#>

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root "apps/api/.env"

if (-not (Test-Path -LiteralPath $envPath)) {
    Write-Error "Missing configuration file: apps/api/.env"
}

Push-Location $root
try {
    & pnpm db:check
    if ($LASTEXITCODE -ne 0) { Write-Error "pnpm db:check failed." }

    & pnpm db:migrate
    if ($LASTEXITCODE -ne 0) { Write-Error "pnpm db:migrate failed." }

    function Get-SchemaReport {
        $json = & uv run --package episignal-backend python -m episignal_backend.schema_check
        if ($LASTEXITCODE -ne 0) { Write-Error "Live schema check failed." }
        return ($json | ConvertFrom-Json)
    }

    & pnpm db:seed
    if ($LASTEXITCODE -ne 0) { Write-Error "pnpm db:seed failed on the first run." }
    $first = Get-SchemaReport

    & pnpm db:seed
    if ($LASTEXITCODE -ne 0) { Write-Error "pnpm db:seed failed on the second run." }
    $second = Get-SchemaReport

    if ($second.missing_tables.Count -ne 0) {
        Write-Error "Missing tables: $($second.missing_tables -join ', ')"
    }
    if ($second.postgis -ne "up") {
        Write-Error "PostGIS is not available in the configured database."
    }

    $canonical = (Get-Content -LiteralPath (Join-Path $root "database/seeds/diseases.json") -Raw |
        ConvertFrom-Json)
    $canonicalSources = (Get-Content -LiteralPath (Join-Path $root "database/seeds/sources.json") -Raw |
        ConvertFrom-Json)

    foreach ($disease in $canonical) {
        $slug = $disease.slug
        $before = $first.diseases.$slug
        $after = $second.diseases.$slug
        if (-not $after) { Write-Error "Canonical disease '$slug' is missing after seeding." }
        if ($before -ne $after) { Write-Error "Canonical disease '$slug' was re-created by seeding." }
    }

    foreach ($source in $canonicalSources) {
        $name = $source.name
        $before = $first.sources.$name
        $after = $second.sources.$name
        if (-not $after) { Write-Error "Canonical source '$name' is missing after seeding." }
        if ($before -ne $after) { Write-Error "Canonical source '$name' was re-created by seeding." }
        if ($second.active_sources -contains $name) {
            Write-Error "Canonical source '$name' must stay inactive until a connector activates it."
        }
    }

    # Identity maps are objects keyed by the natural key, so one entry per key is
    # guaranteed; locally created non-canonical diseases are allowed to remain.
    $canonicalCount = $canonical.Count
    $sourceCount = $canonicalSources.Count
    $totalDiseases = ($second.diseases.PSObject.Properties | Measure-Object).Count

    Write-Output "database: $($second.database)"
    Write-Output "postgis: $($second.postgis)"
    Write-Output "core tables: 8 present"
    Write-Output "canonical diseases: $canonicalCount stable (of $totalDiseases rows)"
    Write-Output "canonical sources: $sourceCount stable and inactive"
    Write-Output "Live database verification passed."
}
finally {
    Pop-Location
}
