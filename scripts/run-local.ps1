$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Model = Join-Path $Root "models\component_classifier.keras"

if (-not (Test-Path $Model)) {
    throw "Model missing: $Model`nRun the notebook and copy component_classifier.keras into models\."
}

Set-Location $Root
docker compose up --build
