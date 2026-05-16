Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptArgs = @($args)
if ($scriptArgs.Count -lt 2) {
    [Console]::Error.WriteLine("usage: scripts/agent-dotnet.ps1 <dotnet-project-dir> <dotnet-args...>")
    [Console]::Error.WriteLine("example: scripts/agent-dotnet.ps1 templates/csharp-dotnet-cli test")
    exit 2
}

$ProjectDir = $scriptArgs[0]
$DotnetArgs = $scriptArgs[1..($scriptArgs.Count - 1)]
$projectRoot = (Resolve-Path $ProjectDir).Path

if (-not $env:DOTNET_CLI_HOME) {
    $env:DOTNET_CLI_HOME = Join-Path $projectRoot ".dotnet"
}
if (-not $env:DOTNET_CLI_TELEMETRY_OPTOUT) {
    $env:DOTNET_CLI_TELEMETRY_OPTOUT = "1"
}
if (-not $env:DOTNET_NOLOGO) {
    $env:DOTNET_NOLOGO = "1"
}
if (-not $env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE) {
    $env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = "1"
}
if (-not $env:NUGET_PACKAGES) {
    $env:NUGET_PACKAGES = Join-Path $projectRoot ".nuget/packages"
}

New-Item -ItemType Directory -Force -Path $env:DOTNET_CLI_HOME, $env:NUGET_PACKAGES | Out-Null
$lockDir = Join-Path $env:DOTNET_CLI_HOME "agent-dotnet.lock"
$locked = $false

try {
    for ($lockWaits = 0; $lockWaits -lt 600; $lockWaits++) {
        try {
            New-Item -ItemType Directory -Path $lockDir -ErrorAction Stop | Out-Null
            $locked = $true
            break
        } catch {
            Start-Sleep -Seconds 1
        }
    }

    if (-not $locked) {
        [Console]::Error.WriteLine("scripts/agent-dotnet.ps1: timed out waiting for project dotnet lock: $lockDir")
        exit 2
    }

    Set-Location $projectRoot
    & dotnet @DotnetArgs
    exit $LASTEXITCODE
} finally {
    if ($locked -and (Test-Path $lockDir)) {
        Remove-Item -Force -Recurse $lockDir
    }
}
