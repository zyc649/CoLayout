param([Parameter(Mandatory=$true)][string]$Workspace,[Parameter(Mandatory=$true)][string]$Icon)
$ErrorActionPreference='Stop'
$entry=Join-Path $Workspace 'tools/project.ps1'
if (-not (Test-Path -LiteralPath $entry) -or -not (Test-Path -LiteralPath $Icon)) { throw 'Workspace launcher or application icon is missing.' }
$shell=New-Object -ComObject WScript.Shell
$link=$shell.CreateShortcut((Join-Path $Workspace 'CoLayout.lnk'))
$link.TargetPath=Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
$link.Arguments='-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$entry+'" -Action start'
$link.WorkingDirectory=$Workspace
$link.IconLocation=$Icon+',0'
$link.Description='CoLayout layout workspace'
$link.WindowStyle=7
$link.Save()
Write-Host 'CoLayout workspace shortcut updated.'
