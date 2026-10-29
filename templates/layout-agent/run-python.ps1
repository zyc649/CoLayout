param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PythonArguments)
$ErrorActionPreference = 'Stop'
$kitDirectory = $PSScriptRoot
$kitInstallationFile = Join-Path $kitDirectory 'installation.json'
if (-not (Test-Path -LiteralPath $kitInstallationFile)) { throw 'Ask the developer to provide the local installation.json.' }
$kitInstallation = Get-Content -LiteralPath $kitInstallationFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($kitInstallation.schema_version -ne 'colayout-customer-runtime-1' -or $kitInstallation.connection_mode -ne 'local-descriptor') { throw 'Ask the developer to update the test-local runtime configuration.' }
$kitPython = [string]$kitInstallation.python_executable
if (-not [System.IO.Path]::IsPathRooted($kitPython)) { throw 'python_executable must be absolute.' }
Set-Location -LiteralPath $kitDirectory
# Ignore Python environment overrides and site/.pth hooks; SDK uses only stdlib.
& $kitPython -E -S -X utf8 @PythonArguments
exit $LASTEXITCODE
