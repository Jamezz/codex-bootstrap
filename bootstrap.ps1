Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-PythonChecked {
    $PythonArgs = @($args)

    $python = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source @PythonArgs
        exit $LASTEXITCODE
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source @PythonArgs
        exit $LASTEXITCODE
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3 @PythonArgs
        exit $LASTEXITCODE
    }

    [Console]::Error.WriteLine("bootstrap.ps1: python3, python, or py is required")
    exit 2
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$bootstrap = Join-Path $repoRoot "bootstrap"
$pythonArgs = @($bootstrap)
$pythonArgs += $args
Invoke-PythonChecked @pythonArgs
