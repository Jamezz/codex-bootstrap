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

function Invoke-Checked {
    $rawArgs = @($args)
    if ($rawArgs.Count -lt 1) {
        [Console]::Error.WriteLine("scripts/check.ps1: missing command")
        exit 2
    }
    $Command = $rawArgs[0]
    $CommandArgs = @()
    if ($rawArgs.Count -gt 1) {
        $CommandArgs = $rawArgs[1..($rawArgs.Count - 1)]
    }

    & $Command @CommandArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
Set-Location $projectRoot

$rulesScript = "tools/supermeta-rules/check.py"
if (-not (Test-Path $rulesScript)) {
    $rulesScript = "../../tools/supermeta-rules/check.py"
}

$agentDotnet = "scripts/agent-dotnet.ps1"
if (-not (Test-Path $agentDotnet)) {
    $agentDotnet = "../../scripts/agent-dotnet.ps1"
}

Invoke-PythonChecked $rulesScript "--config" "supermeta-rules.json" "--root" "." "--skip-callouts"
Invoke-Checked $agentDotnet "." "restore" "--locked-mode"
Invoke-Checked $agentDotnet "." "format" "CsharpDotnetCli.slnx" "--verify-no-changes" "--no-restore"
Invoke-Checked $agentDotnet "." "build" "CsharpDotnetCli.slnx" "--configuration" "Release" "--no-restore"
Invoke-Checked $agentDotnet "." "test" "CsharpDotnetCli.slnx" "--configuration" "Release" "--no-build"
