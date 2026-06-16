Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Show-Usage {
    [Console]::Error.WriteLine("usage: scripts/supermeta-cache.ps1 clean [--project <gradle-project-dir>] [harness-options...]")
    [Console]::Error.WriteLine("       scripts/supermeta-cache.ps1 clean [gradle-project-dir]")
    [Console]::Error.WriteLine("")
    [Console]::Error.WriteLine("Removes persistent Supermeta rules analysis caches without running Gradle.")
}

$scriptArgs = @($args)
if ($scriptArgs.Count -eq 0) {
    $scriptArgs = @("clean")
}

if ($scriptArgs[0] -eq "-h" -or $scriptArgs[0] -eq "--help") {
    Show-Usage
    exit 0
}

if ($scriptArgs[0] -ne "clean") {
    [Console]::Error.WriteLine("scripts/supermeta-cache.ps1: unknown command: $($scriptArgs[0])")
    Show-Usage
    exit 2
}

$projectDir = "."
$projectDirSet = $false
$remaining = New-Object System.Collections.Generic.List[string]
$index = 1
while ($index -lt $scriptArgs.Count) {
    $arg = $scriptArgs[$index]
    if ($arg -eq "-h" -or $arg -eq "--help") {
        Show-Usage
        exit 0
    } elseif ($arg -eq "-p" -or $arg -eq "--project") {
        if (($index + 1) -ge $scriptArgs.Count) {
            [Console]::Error.WriteLine("scripts/supermeta-cache.ps1: $arg requires a value")
            exit 2
        }
        $projectDir = $scriptArgs[$index + 1]
        $projectDirSet = $true
        $index += 2
    } elseif ($arg -eq "--") {
        $index += 1
        while ($index -lt $scriptArgs.Count) {
            $remaining.Add($scriptArgs[$index])
            $index += 1
        }
    } elseif ($arg.StartsWith("-")) {
        while ($index -lt $scriptArgs.Count) {
            $remaining.Add($scriptArgs[$index])
            $index += 1
        }
    } else {
        if ($projectDirSet) {
            [Console]::Error.WriteLine("scripts/supermeta-cache.ps1: unexpected extra project argument: $arg")
            exit 2
        }
        $projectDir = $arg
        $projectDirSet = $true
        $index += 1
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$agentGradle = Join-Path $scriptDir "agent-gradle.ps1"
& $agentGradle $projectDir --clean-supermeta-cache @remaining
exit $LASTEXITCODE
