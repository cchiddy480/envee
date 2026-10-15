$ErrorActionPreference = 'Stop'
$EnveePython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$EnveeCommand = Join-Path $PSScriptRoot '.venv\Scripts\envee.exe'
if (-not (Test-Path $EnveeCommand)) {
    py -3.12 -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $EnveePython -m pip install $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if ($args.Count -eq 0) { & $EnveeCommand init } else { & $EnveeCommand @args }
exit $LASTEXITCODE
