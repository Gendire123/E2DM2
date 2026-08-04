[CmdletBinding()]
param(
    [string]$Version = "1.1.2",
    [string]$Python = "",
    [string]$Ffmpeg = "",
    [string]$Ffprobe = "",
    [string]$InnoCompiler = "",
    [string]$WorkRoot = "",
    [string]$OutputRoot = "",
    [switch]$SkipTests,
    [switch]$SkipInstaller,
    [switch]$CleanBuildToolsAfterCompile,
    [switch]$AzureSign,
    [string]$AzureMetadataPath = "",
    [string]$AzureDlibPath = "",
    [string]$SignToolPath = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $PSBoundParameters.ContainsKey('Version')) {
    $VersionPy = Join-Path $Root "e2dm2\version.py"
    $UiPy = Join-Path $Root "e2dm2\ui.py"
    if (Test-Path -LiteralPath $VersionPy -PathType Leaf) {
        $VersionMatch = Select-String -Path $VersionPy -Pattern '__version__\s*=\s*"([^"]+)"'
        if ($VersionMatch) {
            $Version = $VersionMatch.Matches[0].Groups[1].Value
        }
    }
    if (-not $Version -and (Test-Path -LiteralPath $UiPy -PathType Leaf)) {
        $VersionMatch = Select-String -Path $UiPy -Pattern 'APP_VERSION\s*=\s*"([^"]+)"'
        if ($VersionMatch) {
            $Version = $VersionMatch.Matches[0].Groups[1].Value
        }
    }
}
if (-not $WorkRoot) {
    $WorkRoot = Join-Path $Root "build"
    if ($WorkRoot -match "[^\x00-\x7F]") {
        $WorkRoot = Join-Path $env:SystemDrive "E2DM2-build"
    }
}
if (-not $OutputRoot) { $OutputRoot = Join-Path $Root "dist" }
$BuildRoot = Join-Path $WorkRoot "windows"
$BuildVenv = Join-Path $WorkRoot ".build-venv"
$TempRoot = Join-Path $WorkRoot "temp"
$NuitkaCache = Join-Path $WorkRoot "nuitka-cache"

if (-not $AzureMetadataPath -and $env:AZURE_SIGNING_METADATA) { $AzureMetadataPath = $env:AZURE_SIGNING_METADATA }
if (-not $AzureMetadataPath) {
    $DefaultMeta = Join-Path $PSScriptRoot "azure_signing_metadata.json"
    if (Test-Path -LiteralPath $DefaultMeta -PathType Leaf) { $AzureMetadataPath = $DefaultMeta }
}
if (-not $AzureDlibPath -and $env:AZURE_SIGNING_DLIB) { $AzureDlibPath = $env:AZURE_SIGNING_DLIB }
if (-not $SignToolPath -and $env:SIGNTOOL_PATH) { $SignToolPath = $env:SIGNTOOL_PATH }

if ($env:OS -ne "Windows_NT") {
    throw "This build script produces the Windows distribution and must run on Windows."
}

New-Item -ItemType Directory -Force -Path $WorkRoot, $TempRoot, $NuitkaCache | Out-Null
$env:TEMP = $TempRoot
$env:TMP = $TempRoot
$env:NUITKA_CACHE_DIR = $NuitkaCache
$env:PIP_NO_CACHE_DIR = "1"

if (-not $Python) {
    $PythonRegistry = Get-ItemProperty "HKCU:\Software\Python\PythonCore\3.12\InstallPath" -ErrorAction SilentlyContinue
    if (-not $PythonRegistry) {
        $PythonRegistry = Get-ItemProperty "HKLM:\Software\Python\PythonCore\3.12\InstallPath" -ErrorAction SilentlyContinue
    }
    if ($PythonRegistry) {
        $Python = $PythonRegistry.ExecutablePath
    }
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python 3.12 was not found. Install it, or pass -Python with its full path."
}

$PythonVersion = (& $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($PythonVersion -ne "3.12") {
    throw "The protected Windows build requires Python 3.12; received Python $PythonVersion."
}

if (-not (Test-Path -LiteralPath $BuildVenv -PathType Container)) {
    & $Python -m venv $BuildVenv
}
$BuildPython = Join-Path $BuildVenv "Scripts\python.exe"
& $BuildPython -m pip install --upgrade pip
$Extras = if ($SkipTests) { "build" } else { "build,dev" }
& $BuildPython -m pip install -e "$Root[$Extras]"

if (-not $SkipTests) {
    & $BuildPython -m pytest $Root
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; the distribution was not built." }
}

if (-not $Ffmpeg) {
    $FfmpegCommand = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($FfmpegCommand) { $Ffmpeg = $FfmpegCommand.Source }
}
if (-not $Ffprobe) {
    $FfprobeCommand = Get-Command ffprobe -ErrorAction SilentlyContinue
    if ($FfprobeCommand) { $Ffprobe = $FfprobeCommand.Source }
}
foreach ($Tool in @($Ffmpeg, $Ffprobe)) {
    if (-not $Tool -or -not (Test-Path -LiteralPath $Tool -PathType Leaf)) {
        throw "FFmpeg and FFprobe are required. Put both on PATH or pass -Ffmpeg and -Ffprobe."
    }
}

New-Item -ItemType Directory -Force -Path $BuildRoot, $OutputRoot | Out-Null
$FileSystem = New-Object -ComObject Scripting.FileSystemObject
$Launcher = $FileSystem.GetFile((Join-Path $PSScriptRoot "e2dm2_launcher.py")).ShortPath
$Icon = $FileSystem.GetFile((Join-Path $Root "e2dm2\assets\icons\app-icon.ico")).ShortPath
$NuitkaBuildRoot = $FileSystem.GetFolder($BuildRoot).ShortPath
$NuitkaPython = $FileSystem.GetFile($BuildPython).ShortPath
$NuitkaArgs = @(
    "-m", "nuitka",
    "--mode=standalone",
    "--assume-yes-for-downloads",
    "--disable-cache=ccache",
    "--enable-plugin=pyside6",
    "--include-qt-plugins=platforms,styles,imageformats,iconengines,multimedia,tls",
    "--include-package-data=e2dm2",
    "--nofollow-import-to=tests",
    "--python-flag=isolated",
    "--python-flag=no_docstrings",
    "--windows-console-mode=disable",
    "--windows-icon-from-ico=$Icon",
    "--company-name=E2DM2",
    "--product-name=Easy Epic Drone Movie Maker",
    "--file-description=Easy Epic Drone Movie Maker",
    "--file-version=$Version",
    "--product-version=$Version",
    "--output-filename=E2DM2.exe",
    "--output-dir=$NuitkaBuildRoot",
    "--remove-output",
    $Launcher
)
& $NuitkaPython @NuitkaArgs
if ($LASTEXITCODE -ne 0) { throw "Nuitka failed to compile E2DM2." }

if ($CleanBuildToolsAfterCompile) {
    foreach ($CleanupTarget in @($BuildVenv, $NuitkaCache, (Join-Path $BuildRoot "e2dm2_launcher.build"))) {
        if (Test-Path -LiteralPath $CleanupTarget) {
            $ResolvedTarget = (Resolve-Path -LiteralPath $CleanupTarget).Path
            $ResolvedWorkRoot = (Resolve-Path -LiteralPath $WorkRoot).Path.TrimEnd('\')
            if (-not $ResolvedTarget.StartsWith($ResolvedWorkRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to clean a path outside the build workspace: $ResolvedTarget"
            }
            Remove-Item -LiteralPath $ResolvedTarget -Recurse -Force
        }
    }
}

$AppExe = Get-ChildItem -LiteralPath $BuildRoot -Filter "E2DM2.exe" -Recurse -File |
    Where-Object { $_.Directory.Name.EndsWith(".dist") } |
    Select-Object -First 1
if (-not $AppExe) { throw "Nuitka completed but E2DM2.exe was not found." }
$DistDir = $AppExe.Directory.FullName

if ($AzureSign) {
    if (-not $SignToolPath) {
        $SignToolCommand = Get-Command signtool.exe -ErrorAction SilentlyContinue
        if ($SignToolCommand) {
            $SignToolPath = $SignToolCommand.Source
        } else {
            $SdkPaths = @(
                (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin\*\x64\signtool.exe"),
                (Join-Path $env:ProgramFiles "Windows Kits\10\bin\*\x64\signtool.exe")
            )
            $ResolvedPaths = Resolve-Path $SdkPaths -ErrorAction SilentlyContinue
            if ($ResolvedPaths) {
                $SignToolPath = $ResolvedPaths | Sort-Object Path -Descending | Select-Object -First 1 | ForEach-Object { $_.Path }
            }
        }
    }
    if (-not $SignToolPath -or -not (Test-Path $SignToolPath)) {
        throw "signtool.exe not found. Install Windows SDK or pass -SignToolPath."
    }

    if (-not $AzureDlibPath) {
        $DlibCandidates = @(
            (Join-Path $env:LOCALAPPDATA "Microsoft\MicrosoftTrustedSigningClientTools\Azure.CodeSigning.Dlib.dll"),
            (Join-Path ${env:ProgramFiles} "Microsoft Trusted Signing Client Tools\bin\x64\Azure.CodeSigning.Dlib.dll"),
            (Join-Path ${env:ProgramFiles(x86)} "Microsoft Trusted Signing Client Tools\bin\x64\Azure.CodeSigning.Dlib.dll")
        )
        $AzureDlibPath = $DlibCandidates | Where-Object { Test-Path $_ -PathType Leaf } | Select-Object -First 1
    }
    if (-not $AzureDlibPath -or -not (Test-Path $AzureDlibPath)) {
        throw "Azure.CodeSigning.Dlib.dll not found. Run 'winget install Microsoft.Azure.TrustedSigningClientTools' or pass -AzureDlibPath."
    }

    if (-not $AzureMetadataPath -or -not (Test-Path $AzureMetadataPath)) {
        throw "Azure Signing metadata JSON file is required for signing. Pass -AzureMetadataPath."
    }

    Write-Host "Signing application executable..."
    & $SignToolPath sign /v /debug /fd SHA256 /tr "http://timestamp.acs.microsoft.com" /td SHA256 /dlib $AzureDlibPath /dmdf $AzureMetadataPath $AppExe.FullName
    if ($LASTEXITCODE -ne 0) { throw "Failed to sign E2DM2.exe" }
}

$ToolDir = Join-Path $DistDir "bin"
$LicenseDir = Join-Path $DistDir "licenses\FFmpeg"
New-Item -ItemType Directory -Force -Path $ToolDir, $LicenseDir | Out-Null
Copy-Item -LiteralPath $Ffmpeg -Destination (Join-Path $ToolDir "ffmpeg.exe") -Force
Copy-Item -LiteralPath $Ffprobe -Destination (Join-Path $ToolDir "ffprobe.exe") -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "THIRD-PARTY-NOTICES.txt") -Destination $DistDir -Force

$FfmpegRoot = Split-Path (Split-Path $Ffmpeg -Parent) -Parent
foreach ($NoticeName in @("LICENSE", "README.txt")) {
    $Notice = Join-Path $FfmpegRoot $NoticeName
    if (Test-Path -LiteralPath $Notice -PathType Leaf) {
        Copy-Item -LiteralPath $Notice -Destination $LicenseDir -Force
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $LicenseDir "LICENSE") -PathType Leaf)) {
    throw "The FFmpeg distributor LICENSE file was not found. Refusing to create a redistributable package."
}

$SourceFiles = Get-ChildItem -LiteralPath $DistDir -Recurse -File |
    Where-Object { $_.Extension -in @(".py", ".pyc") }
if ($SourceFiles) {
    throw "Protected build verification failed: Python source or bytecode exists in the distribution."
}
& (Join-Path $ToolDir "ffmpeg.exe") -version | Select-Object -First 1
& (Join-Path $ToolDir "ffprobe.exe") -version | Select-Object -First 1

if (-not $SkipInstaller) {
    if (-not $InnoCompiler) {
        $InnoCandidates = @(
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
        )
        $InnoCompiler = $InnoCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    }
    if (-not $InnoCompiler) {
        throw "Inno Setup 6 is required for the installer. Install it or pass -InnoCompiler. The standalone app is ready at $DistDir."
    }
    $InstallerScript = Join-Path $PSScriptRoot "installer.iss"
    & $InnoCompiler "/DAppVersion=$Version" "/DDistDir=$DistDir" "/DOutputDir=$OutputRoot" $InstallerScript
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed to create the installer." }

    if ($AzureSign) {
        $InstallerPath = Join-Path $OutputRoot "E2DM2-Setup-$Version.exe"
        Write-Host "Signing installer..."
        & $SignToolPath sign /v /debug /fd SHA256 /tr "http://timestamp.acs.microsoft.com" /td SHA256 /dlib $AzureDlibPath /dmdf $AzureMetadataPath $InstallerPath
        if ($LASTEXITCODE -ne 0) { throw "Failed to sign installer: $InstallerPath" }
    }
}

Write-Host "Standalone application: $DistDir"
if (-not $SkipInstaller) {
    $InstallerPath = Join-Path $OutputRoot "E2DM2-Setup-$Version.exe"
    Write-Host "Installer: $InstallerPath"
    
    if (Test-Path -LiteralPath $InstallerPath) {
        $GitHubReleasePublished = $false
        $VirusTotalUploaded = $false

        # GitHub Release Automation
        if (Get-Command gh -ErrorAction SilentlyContinue) {
            $NotesFile = Join-Path $PSScriptRoot "latest_release_notes.md"
            if (-not (Test-Path -LiteralPath $NotesFile)) {
                New-Item -ItemType File -Path $NotesFile -Value "We are excited to release E2DM2 v$Version!`n`n## Download & Installation`n1. Download E2DM2-Setup-$Version.exe from the assets section below." -Force | Out-Null
            }

            # Prepend the release title to the release notes in a temporary file
            $TempNotesFile = Join-Path $TempRoot "github_release_notes.md"
            $Header = "## Easy Epic Drone Movie Maker (E2DM2) - v$Version`n`n"
            $Content = [System.IO.File]::ReadAllText($NotesFile)
            $FullNotes = $Header + $Content
            [System.IO.File]::WriteAllText($TempNotesFile, $FullNotes, [System.Text.Encoding]::UTF8)

            Write-Host "Creating GitHub Release and uploading installer..."
            gh release create "v$Version" $InstallerPath --repo "Gendire123/E2DM2" --title "v$Version" --notes-file $TempNotesFile
            if ($LASTEXITCODE -eq 0) {
                Write-Host "GitHub Release created successfully!"
                $GitHubReleasePublished = $true
            } else {
                Write-Warning "GitHub CLI release creation returned exit code $LASTEXITCODE (release may already exist)."
            }
        } else {
            Write-Warning "GitHub CLI (gh) is not installed. Skipping automatic GitHub Release creation."
        }

        # VirusTotal Upload Automation
        if ($env:VIRUSTOTAL_API_KEY) {
            Write-Host "Starting automated VirusTotal scan upload..."
            & $BuildPython (Join-Path $PSScriptRoot "upload_virustotal.py") $InstallerPath
            if ($LASTEXITCODE -eq 0) {
                Write-Host "VirusTotal upload completed successfully!"
                $VirusTotalUploaded = $true
            } else {
                Write-Error "VirusTotal upload failed."
            }
        } else {
            Write-Warning "VIRUSTOTAL_API_KEY environment variable is not set. Skipping automatic VirusTotal upload."
        }

        # Publish one atomic release manifest only after the installer exists at
        # GitHub and has been accepted by VirusTotal. The website reads this
        # manifest at runtime, so a Netlify deployment is no longer required.
        if ($GitHubReleasePublished -and $VirusTotalUploaded) {
            if ($env:SUPABASE_RELEASE_PUBLISH_TOKEN) {
                Write-Host "Publishing release metadata to Supabase..."
                & $BuildPython (Join-Path $PSScriptRoot "publish_release.py") $Version $InstallerPath
                if ($LASTEXITCODE -ne 0) {
                    Write-Error "Supabase release metadata publish failed."
                }
            } else {
                Write-Warning "SUPABASE_RELEASE_PUBLISH_TOKEN is not set. The website will continue showing the previous release."
            }
        } else {
            Write-Warning "Release metadata was not published because GitHub and VirusTotal did not both complete successfully."
        }
    }
}
$global:LASTEXITCODE = 0
