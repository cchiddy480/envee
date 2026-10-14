$ErrorActionPreference = 'Stop'
$ForgePython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$ForgeCommand = Join-Path $PSScriptRoot '.venv\Scripts\forge.exe'
if (-not (Test-Path $ForgeCommand)) {
    py -3.12 -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $ForgePython -m pip install $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if ($args.Count -eq 0) { & $ForgeCommand init } else { & $ForgeCommand @args }
exit $LASTEXITCODE
