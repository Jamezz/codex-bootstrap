param(
    [Parameter(Position = 0)]
    [string] $ProjectSlug,

    [string] $Template = "java-gradle-cli",
    [string] $Package = "",
    [string] $Repo = "https://github.com/Jamezz/codex-bootstrap.git",
    [string] $Ref = "main",
    [string] $Dir = (Get-Location).Path,
    [switch] $Force,
    [switch] $DryRun,
    [switch] $ListTemplates,
    [string] $TemplatesFile = "",
    [switch] $Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Show-CodexBootstrapUsage {
    @"
Codex Bootstrap Windows installer

Usage:
  .\install.ps1 <project-slug> [options]
  .\install.ps1 -ListTemplates [-TemplatesFile path]

Options:
  -Template <id>          Template id to materialize. Defaults to java-gradle-cli.
  -Package <name>         Java package name. Java templates derive com.generated.<slug> when omitted.
  -Repo <url>             Bootstrap catalog Git URL. Defaults to https://github.com/Jamezz/codex-bootstrap.git.
  -Ref <ref>              Git ref to install from. Defaults to main.
  -Dir <path>             Parent directory for the generated project. Defaults to the current directory.
  -Force                  Replace an existing target project directory.
  -DryRun                 Print the install plan without cloning or changing files.
  -ListTemplates          List templates from GitHub Pages or -TemplatesFile.
  -TemplatesFile <path>   Read template metadata from a local templates.json file.
  -Help                   Show this help.

Examples:
  .\install.ps1 my-app -Template python-uv-cli
  .\install.ps1 my-app -Template csharp-dotnet-cli
  .\install.ps1 my-app -Template rust-cargo-cli
  .\install.ps1 my-app -Template java-gradle-cli -Package com.acme.myapp

Remote function form:
  irm https://jamezz.github.io/codex-bootstrap/install.ps1 | iex
  Install-CodexBootstrap my-app -Template python-uv-cli
"@
}

function Stop-CodexBootstrap {
    param([string] $Message)
    [Console]::Error.WriteLine("codex-bootstrap installer: $Message")
    exit 2
}

function Resolve-RequiredCommand {
    param([string] $Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        Stop-CodexBootstrap "$Name is required"
    }
    return $command.Source
}

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

    Stop-CodexBootstrap "python3, python, or py is required"
}

function Test-ProjectSlug {
    param([string] $Value)
    return $Value -match '^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$'
}

function Test-JavaPackage {
    param([string] $Value)
    $javaKeywords = @(
        "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
        "class", "const", "continue", "default", "do", "double", "else", "enum",
        "extends", "final", "finally", "float", "for", "goto", "if", "implements",
        "import", "instanceof", "int", "interface", "long", "native", "new",
        "package", "private", "protected", "public", "return", "short", "static",
        "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
        "transient", "try", "void", "volatile", "while"
    )
    $parts = $Value -split '\.'
    if ($parts.Count -lt 2) { return $false }
    foreach ($part in $parts) {
        if ($part -notmatch '^[a-z][a-z0-9_]*$') { return $false }
        if ($javaKeywords -contains $part) { return $false }
    }
    return $true
}

function Get-DerivedJavaPackage {
    param([string] $Slug)
    $segment = $Slug -replace '-', ''
    $derived = "com.generated.$segment"
    if (-not (Test-JavaPackage $derived)) {
        Stop-CodexBootstrap "cannot derive a valid Java package from '$Slug'; pass -Package"
    }
    return $derived
}

function Show-TemplateMetadata {
    param(
        [string] $TemplatesFile,
        [string] $PagesUrl
    )
    if ($TemplatesFile) {
        if (-not (Test-Path $TemplatesFile)) {
            Stop-CodexBootstrap "templates file not found: $TemplatesFile"
        }
        $payload = Get-Content -Raw -Path $TemplatesFile | ConvertFrom-Json
    } else {
        $payload = Invoke-RestMethod "$PagesUrl/templates.json"
    }

    foreach ($template in $payload.templates) {
        $required = $template.requiredInputs -join ", "
        $suffix = if ($required) { " (requires: $required)" } else { "" }
        Write-Output "$($template.id): $($template.displayName)$suffix"
    }
}

function Install-CodexBootstrap {
    param(
        [Parameter(Position = 0)]
        [string] $ProjectSlug,

        [string] $Template = "java-gradle-cli",
        [string] $Package = "",
        [string] $Repo = "https://github.com/Jamezz/codex-bootstrap.git",
        [string] $Ref = "main",
        [string] $Dir = (Get-Location).Path,
        [switch] $Force,
        [switch] $DryRun,
        [switch] $ListTemplates,
        [string] $TemplatesFile = "",
        [switch] $Help,
        [string] $PagesUrl = "https://jamezz.github.io/codex-bootstrap"
    )

    if ($Help) {
        Show-CodexBootstrapUsage
        return
    }

    if ($ListTemplates) {
        Show-TemplateMetadata -TemplatesFile $TemplatesFile -PagesUrl $PagesUrl
        return
    }

    if (-not $ProjectSlug) {
        Stop-CodexBootstrap "missing required project slug"
    }
    if (-not (Test-ProjectSlug $ProjectSlug)) {
        Stop-CodexBootstrap "project slug must be lowercase hyphenated, like my-app"
    }

    $knownTemplates = @(
        "csharp-dotnet-cli",
        "existing-repo-control",
        "java-gradle-cli",
        "python-uv-cli",
        "rust-cargo-cli",
        "typescript-bun-cli",
        "typescript-bun-mcp-server"
    )
    if ($knownTemplates -notcontains $Template) {
        Stop-CodexBootstrap "unknown template '$Template'; run -ListTemplates"
    }

    if ($Template -eq "java-gradle-cli") {
        if (-not $Package) {
            $Package = Get-DerivedJavaPackage $ProjectSlug
        } elseif (-not (Test-JavaPackage $Package)) {
            Stop-CodexBootstrap "invalid Java package: $Package"
        }
    } elseif ($Package) {
        Stop-CodexBootstrap "-Package is only supported by java-gradle-cli"
    }

    $targetParent = if ([System.IO.Path]::IsPathRooted($Dir)) {
        $Dir
    } else {
        Join-Path (Get-Location).Path $Dir
    }
    $targetDir = Join-Path $targetParent $ProjectSlug

    if ($DryRun) {
        Write-Output "Install plan:"
        Write-Output "  repo: $Repo"
        Write-Output "  ref: $Ref"
        Write-Output "  template: $Template"
        Write-Output "  project: $ProjectSlug"
        Write-Output "  target: $targetDir"
        if ($Template -eq "java-gradle-cli") {
            Write-Output "  package: $Package"
        }
        if ((Test-Path $targetDir) -and -not $Force) {
            Write-Output "  target-status: exists and would be refused without -Force"
        }
        return
    }

    Resolve-RequiredCommand "git" | Out-Null
    New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
    $targetParent = (Resolve-Path $targetParent).Path
    $targetDir = Join-Path $targetParent $ProjectSlug

    if ((Test-Path $targetDir) -and -not $Force) {
        Stop-CodexBootstrap "target already exists: $targetDir; pass -Force to replace it"
    }

    $tmpDir = Join-Path $targetParent ".codex-bootstrap.$([System.Guid]::NewGuid().ToString('N').Substring(0, 8))"
    try {
        & git clone --depth 1 $Repo $tmpDir
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        & git -C $tmpDir checkout --detach $Ref *> $null
        if ($LASTEXITCODE -ne 0) {
            & git -C $tmpDir fetch --depth 1 origin $Ref
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            & git -C $tmpDir checkout --detach FETCH_HEAD
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }

        $bootstrapArgs = @(
            "bootstrap",
            "--template", $Template,
            "--name", $ProjectSlug,
            "--yes"
        )
        if ($Template -eq "java-gradle-cli") {
            $bootstrapArgs += @("--package", $Package)
        }

        Push-Location $tmpDir
        try {
            Invoke-PythonChecked @bootstrapArgs
        } finally {
            Pop-Location
        }

        if (Test-Path $targetDir) {
            Remove-Item -Force -Recurse $targetDir
        }
        Move-Item $tmpDir $targetDir
        $tmpDir = ""

        Write-Output "Created $targetDir from $Template ($Ref)."
    } finally {
        if ($tmpDir -and (Test-Path $tmpDir)) {
            Remove-Item -Force -Recurse $tmpDir
        }
    }
}

if ($ProjectSlug -or $Help -or $ListTemplates) {
    Install-CodexBootstrap @PSBoundParameters
}
