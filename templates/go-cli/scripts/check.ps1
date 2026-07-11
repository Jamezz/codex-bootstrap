Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-PythonChecked {
    $PythonArgs = @($args)

    $python = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source @PythonArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        return
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source @PythonArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        return
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3 @PythonArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        return
    }

    [Console]::Error.WriteLine("scripts/check.ps1: python3, python, or py is required")
    exit 2
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
Set-Location $projectRoot

$rulesScript = "tools/supermeta-rules/check.py"
if (-not (Test-Path $rulesScript)) {
    $rulesScript = "../../tools/supermeta-rules/check.py"
}

Invoke-PythonChecked $rulesScript "--config" "supermeta-rules.json" "--root" "."

