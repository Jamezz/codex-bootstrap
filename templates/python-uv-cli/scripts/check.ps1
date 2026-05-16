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

function Invoke-PythonCapture {
    $PythonArgs = @($args)

    $python = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python) {
        $output = & $python.Source @PythonArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        return $output
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $output = & $python.Source @PythonArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        return $output
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $output = & $py.Source -3 @PythonArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        return $output
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

$env:UV_NO_EDITABLE = "1"
$projectName = (Invoke-PythonCapture "-c" "import pathlib, tomllib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))['project']['name'])").Trim()

$rulesScript = "tools/supermeta-rules/check.py"
if (-not (Test-Path $rulesScript)) {
    $rulesScript = "../../tools/supermeta-rules/check.py"
}

Invoke-PythonChecked $rulesScript "--config" "supermeta-rules.json" "--root" "." "--skip-callouts"
Invoke-Checked "uv" "sync" "--locked" "--no-editable" "--reinstall-package" $projectName
Invoke-Checked "uv" "run" "ruff" "format" "--check" "src" "tests"
Invoke-Checked "uv" "run" "ruff" "check" "src" "tests"
Invoke-Checked "uv" "run" "mypy" "src" "tests"
Invoke-Checked "uv" "run" "pytest"
