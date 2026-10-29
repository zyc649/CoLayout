param([string]$Python='3.13',[string]$BridgeArchive='')
$ErrorActionPreference='Stop'
$repo=$PSScriptRoot
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is required. See docs/en/setup.md or docs/zh/setup.md.' }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv is required: https://docs.astral.sh/uv/getting-started/installation/ . Ask your setup agent to install it, then retry.' }
$pythonExe=Join-Path $repo '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    & uv venv --python $Python (Join-Path $repo '.venv')
    if ($LASTEXITCODE) { throw 'Python environment creation failed.' }
}
& $pythonExe -c "import sys; assert sys.version_info[:2] == (3,13), 'Use Python 3.13'"
if ($LASTEXITCODE) { throw 'Wrong Python version.' }
$bridgeArguments=@((Join-Path $repo 'tools/bootstrap_bridge.py'))
if ($BridgeArchive) { $bridgeArguments+=@('--archive',$BridgeArchive) }
& $pythonExe @bridgeArguments
if ($LASTEXITCODE) { throw 'Pinned Bridge preparation failed.' }
& uv pip install --python $pythonExe -r (Join-Path $repo 'requirements-locked.txt')
if ($LASTEXITCODE) { throw 'Dependency installation failed.' }
& uv pip install --python $pythonExe --no-deps (Join-Path $repo '.colayout/dependencies/virtuoso-bridge')
if ($LASTEXITCODE) { throw 'Bridge installation failed.' }
& uv pip install --python $pythonExe --no-deps -e $repo
if ($LASTEXITCODE) { throw 'CoLayout installation failed.' }
Push-Location -LiteralPath $repo
try {
    & $pythonExe -X utf8 -m colayout_lite.bootstrap init
    if ($LASTEXITCODE) { throw 'Local initialization failed.' }
    & $pythonExe -X utf8 tools/check_environment.py
    if ($LASTEXITCODE) { throw 'Environment verification failed.' }
} finally { Pop-Location }
Write-Host 'Installed. Continue with AGENTS.md or docs/en/setup.md. No server or layout was changed.'
