# Run GridLens from a source checkout on Windows, as run_app.sh does on Linux:
#     powershell -ExecutionPolicy Bypass -File scripts\run_app.ps1
# Uses .venv\Scripts\python.exe when it exists, and python otherwise.
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONPATH = (Join-Path $Root "src") + [IO.Path]::PathSeparator + $env:PYTHONPATH
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}
& $Python -m gridlens
exit $LASTEXITCODE
