param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$Scratch
)
$ErrorActionPreference = 'Stop'
if (-not [IO.Path]::IsPathRooted($Scratch)) { throw 'Scratch must be an absolute approved temporary root' }
$Run = Join-Path $Scratch ('crystal-ball-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Run | Out-Null
$env:TMP = $Run
$env:TEMP = $Run
$env:TMPDIR = $Run
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location -LiteralPath $Repo
try {
    & git rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Output "Command: $Python -m pytest -m 'not live' -q -p no:cacheprovider --basetemp $Run/pytest"
    & $Python -m pytest -m 'not live' -q -p no:cacheprovider --basetemp (Join-Path $Run 'pytest')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python scripts/privacy_scan.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python scripts/build_release.py
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
