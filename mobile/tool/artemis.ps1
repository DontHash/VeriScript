param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
$ErrorActionPreference = 'Stop'
$mobileRoot = Split-Path $PSScriptRoot -Parent
$runtimePath = Join-Path $mobileRoot '.artemis-runtime'
$pythonPath = Join-Path $mobileRoot '.artemis-venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) { throw 'Run python tool/artemis_bootstrap.py first.' }
$oldPythonPath = $env:PYTHONPATH
$oldAppDir = $env:ARTEMIS_APP_DIR
$oldSdk = $env:ANDROID_HOME
$oldPath = $env:PATH
try {
    $env:PYTHONPATH = $runtimePath
    $env:ARTEMIS_APP_DIR = Join-Path $runtimePath 'local-state'
    if (!$env:ANDROID_HOME) { $env:ANDROID_HOME = 'D:\Android\Sdk' }
    $env:PATH = "$($env:ANDROID_HOME)\platform-tools;$oldPath"
    Push-Location $runtimePath
    try { & $pythonPath -m artemis @Arguments }
    finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "Artemis exited with code $LASTEXITCODE" }
} finally {
    $env:PYTHONPATH = $oldPythonPath
    $env:ARTEMIS_APP_DIR = $oldAppDir
    $env:ANDROID_HOME = $oldSdk
    $env:PATH = $oldPath
}
