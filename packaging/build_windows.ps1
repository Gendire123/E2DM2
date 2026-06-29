[CmdletBinding()]
param(
    [string]$Version = "0.1.0",
    [string]$Python = "",
    [string]$Ffmpeg = "",
    [string]$Ffprobe = "",
    [string]$InnoCompiler = "",
    [string]$WorkRoot = "",
    [string]$OutputRoot = "",
    [switch]$SkipTests,
    [switch]$SkipInstaller,
    [switch]$CleanBuildToolsAfterCompile
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
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
}

Write-Host "Standalone application: $DistDir"
if (-not $SkipInstaller) {
    Write-Host "Installer: $(Join-Path $OutputRoot "E2DM2-Setup-$Version.exe")"
}
