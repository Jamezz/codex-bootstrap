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

    [Console]::Error.WriteLine("scripts/agent-bootstrap.ps1: python3, python, or py is required")
    exit 2
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path

if ($args.Count -gt 0 -and $args[0] -eq "check-updates") {
    $nagWrapper = Join-Path $repoRoot "scripts/agent-nag.ps1"
    if (Test-Path $nagWrapper) {
        $remainingArgs = @()
        if ($args.Count -gt 1) {
            $remainingArgs = $args[1..($args.Count - 1)]
        }
        & $nagWrapper check-updates @remainingArgs
        exit $LASTEXITCODE
    }
}

if ($args.Count -gt 0 -and $args[0] -eq "adopt") {
    $adoptScript = Join-Path $repoRoot "tools/supermeta-bootstrap/bootstrap_adopt.py"
    $remainingArgs = @()
    if ($args.Count -gt 1) {
        $remainingArgs = $args[1..($args.Count - 1)]
    }
    $pythonArgs = @($adoptScript)
    $pythonArgs += $remainingArgs
    Invoke-PythonChecked @pythonArgs
}

$syncScript = Join-Path $repoRoot "tools/supermeta-bootstrap/bootstrap_sync.py"
$pythonArgs = @($syncScript)
$pythonArgs += $args
Invoke-PythonChecked @pythonArgs
