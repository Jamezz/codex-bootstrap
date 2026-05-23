Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptArgs = @($args)
if ($scriptArgs.Count -lt 2) {
    [Console]::Error.WriteLine("usage: scripts/agent-gradle.ps1 <gradle-project-dir> <gradle-args...>")
    [Console]::Error.WriteLine("       scripts/agent-gradle.ps1 <gradle-project-dir> --ps|--logs|--stop|--kill")
    [Console]::Error.WriteLine("example: scripts/agent-gradle.ps1 . test")
    exit 2
}

$ProjectDir = $scriptArgs[0]
$GradleArgs = $scriptArgs[1..($scriptArgs.Count - 1)]

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

    [Console]::Error.WriteLine("scripts/agent-gradle.ps1: python3, python, or py is required")
    exit 2
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$gradleScript = Join-Path $repoRoot "tools/supermeta-gradle/gradle.py"
$pythonArgs = @($gradleScript, "--project", $ProjectDir)

if (@("--ps", "--logs", "--stop", "--kill") -contains $GradleArgs[0]) {
    $pythonArgs += $GradleArgs
} else {
    $pythonArgs += "--"
    $pythonArgs += $GradleArgs
}

Invoke-PythonChecked @pythonArgs
