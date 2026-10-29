param([ValidateSet('start','status','publish','test','doctor')][string]$Action='status')
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
$python=Join-Path $repo '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup.ps1 first.' }
Push-Location -LiteralPath $repo
try {
    if ($Action -eq 'test') {
        $env:QT_QPA_PLATFORM='windows'
        & $python -X utf8 -m pytest tests_lite -q
        if ($LASTEXITCODE) { throw 'Regression failed.' }
        return
    }
    if ($Action -in @('status','doctor')) {
        & $python -X utf8 -m colayout_lite.bootstrap $Action
        if ($LASTEXITCODE) { throw 'Read the reported setup diagnosis.' }
        return
    }
    $pointer=Join-Path $repo '.colayout/installation.json'
    if (-not (Test-Path -LiteralPath $pointer)) { throw 'Run setup.ps1 first.' }
    $settings=Get-Content -LiteralPath $pointer -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Action -eq 'publish') {
        & $python -X utf8 -m tools.publish_test_connection --installation $pointer
        if ($LASTEXITCODE) { throw 'Connection publication failed; no client state was reset.' }
        return
    }
    $existing=Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'colayout_lite.workspace_app' -and
        $_.CommandLine.Contains($pointer)
    }
    if ($existing) { Write-Host 'This installation already has an APP process; no second writer started.'; return }
    $pythonw=Join-Path $repo '.venv/Scripts/pythonw.exe'
    $documentArgument='"'+([string]$settings.document)+'"'
    $pointerArgument='"'+$pointer+'"'
    $process=Start-Process -FilePath $pythonw -ArgumentList @('-m','colayout_lite.workspace_app',$documentArgument,'--agent-api','--installation',$pointerArgument) -WorkingDirectory $repo -WindowStyle Hidden -PassThru
    Write-Host "CoLayout started (launcher PID $($process.Id)). Use status to check readiness."
} finally { Pop-Location }
