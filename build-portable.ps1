param(
    [string]$Python = 'python',
    [string]$YtDlp = 'yt-dlp',
    [string]$FFmpeg = 'ffmpeg',
    [string]$FFprobe = 'ffprobe',
    [string]$Deno = 'deno',
    [string]$NcmDump = 'ncmdump',
    [string]$NcmDumpLicense,
    [string]$FFmpegLicense,
    [string]$ChromiumDirectory,
    [string]$BuildPythonPath,
    [string]$DestinationRoot = (Join-Path $PSScriptRoot 'dist')
)

$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$build = Join-Path $project '.build'
$dist = $DestinationRoot

function Find-Application([string]$Name) {
    if (Test-Path -LiteralPath $Name -PathType Leaf) {
        return (Resolve-Path -LiteralPath $Name).Path
    }
    return (Get-Command $Name -CommandType Application -ErrorAction Stop).Source
}

$ytDlpPath = Find-Application $YtDlp
$ffmpegPath = Find-Application $FFmpeg
$ffprobePath = Find-Application $FFprobe
$denoPath = Find-Application $Deno
$ncmDumpPath = Find-Application $NcmDump
if (-not $NcmDumpLicense) {
    $NcmDumpLicense = Join-Path (Split-Path $ncmDumpPath) 'LICENSE.txt'
}
if (-not (Test-Path -LiteralPath $NcmDumpLicense -PathType Leaf)) {
    throw 'Set -NcmDumpLicense to the LICENSE.txt from the ncmdump release source.'
}
if (-not $ChromiumDirectory) {
    $shell = & $Python -c "from playwright.sync_api import sync_playwright; from pathlib import Path; p = sync_playwright().start(); c = Path(p.chromium.executable_path); print(next(c.parent.parent.parent.glob('chromium_headless_shell-*/chrome-headless-shell-win64'), '')); p.stop()"
    if ($LASTEXITCODE -ne 0 -or -not $shell) { throw 'Set -ChromiumDirectory to the Playwright Chromium headless shell directory.' }
    $ChromiumDirectory = $shell
}
if (-not (Test-Path -LiteralPath (Join-Path $ChromiumDirectory 'chrome-headless-shell.exe') -PathType Leaf)) {
    throw 'Chromium headless shell is missing.'
}

$previous = $env:PYTHONPATH
$previousUtf8 = $env:PYTHONUTF8
try {
    if ($BuildPythonPath) { $env:PYTHONPATH = $BuildPythonPath }
    $env:PYTHONUTF8 = '1'
    $pdfLicenses = & $Python -B -c 'from importlib.metadata import files; print(next(p for p in files("pypdfium2") if p.name == "METADATA").locate().parent / "licenses")'
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pdfLicenses -PathType Container)) {
        throw 'Install pypdfium2 from requirements-build.txt to provide the PDFium renderer and licenses.'
    }
    & $Python -B -m PyInstaller --noconfirm --workpath $build --distpath $dist (Join-Path $project 'portable.spec')
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller exited with code $LASTEXITCODE." }
} finally {
    $env:PYTHONPATH = $previous
    $env:PYTHONUTF8 = $previousUtf8
}

$release = Join-Path $dist '图影盒v1.1.4-便携版'
$tools = Join-Path $release 'tools'
New-Item -ItemType Directory -Path $tools -Force | Out-Null
Copy-Item -LiteralPath $ytDlpPath -Destination (Join-Path $tools 'yt-dlp.exe')
Copy-Item -LiteralPath $ffmpegPath -Destination (Join-Path $tools 'ffmpeg.exe')
Copy-Item -LiteralPath $ffprobePath -Destination (Join-Path $tools 'ffprobe.exe')
Copy-Item -LiteralPath $denoPath -Destination (Join-Path $tools 'deno.exe')
Copy-Item -LiteralPath $ncmDumpPath -Destination (Join-Path $tools 'ncmdump.exe')
Copy-Item -LiteralPath $ChromiumDirectory -Destination (Join-Path $tools 'chromium') -Recurse

$notices = Join-Path $release 'licenses'
New-Item -ItemType Directory -Path $notices -Force | Out-Null
$pythonLicense = & $Python -B -c 'import sys; from pathlib import Path; print(Path(sys.base_prefix) / "LICENSE.txt")'
if (Test-Path -LiteralPath $pythonLicense) {
    Copy-Item -LiteralPath $pythonLicense -Destination (Join-Path $notices 'Python.txt')
}
if (-not $FFmpegLicense) {
    $FFmpegLicense = Join-Path (Split-Path (Split-Path $ffmpegPath)) 'LICENSE'
}
if (Test-Path -LiteralPath $FFmpegLicense -PathType Leaf) {
    Copy-Item -LiteralPath $FFmpegLicense -Destination (Join-Path $notices 'FFmpeg.txt')
}
Copy-Item -LiteralPath $NcmDumpLicense -Destination (Join-Path $notices 'ncmdump.txt')
Copy-Item -LiteralPath $pdfLicenses -Destination (Join-Path $notices 'pypdfium2') -Recurse
$pythonPackages = & $Python -B -c 'import sysconfig; print(sysconfig.get_path("purelib"))'
foreach ($package in @('gallery_dl', 'pillow', 'requests', 'certifi', 'charset_normalizer', 'idna', 'urllib3', 'playwright', 'tkinterdnd2', 'greenlet', 'pyee')) {
    foreach ($metadata in Get-ChildItem -LiteralPath $pythonPackages -Directory -Filter "$package-*.dist-info") {
        $folder = Join-Path $notices $metadata.Name
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
        Get-ChildItem -LiteralPath $metadata.FullName | Where-Object Name -Match '^(licen[sc]es?|copying|notice)' |
            Copy-Item -Destination $folder -Recurse
    }
}
Copy-Item -LiteralPath (Join-Path $project '使用说明.txt') -Destination $release
Copy-Item -LiteralPath (Join-Path $project 'THIRD_PARTY_NOTICES.md') -Destination $release
Copy-Item -LiteralPath (Join-Path $project 'CHANGELOG.md') -Destination $release
Write-Output $release
