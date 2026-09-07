# ============================================================================
# Register (or update) the Windows Task Scheduler task that runs the Allen &
# Co Custom Action API watchdog (infra/allenco/run_api.ps1) every few minutes
# on the Managed Windows Instance. IIS reverse-proxies the public hostname to
# the uvicorn process this watchdog keeps alive; IIS does not manage that
# process itself, hence the recurring check.
#
# Idempotent: re-running updates the existing task (-Force).
#
# Usage (run in an ELEVATED PowerShell):
#   ./infra/allenco/register-api-watchdog-task.ps1
#   ./infra/allenco/register-api-watchdog-task.ps1 -IntervalMinutes 10 -AsSystem
#   ./infra/allenco/register-api-watchdog-task.ps1 -RunAsUser 'ALLENCO\svc-glean'
# ============================================================================
param(
  [string]$TaskName = 'AllenCo-Glean-API-Watchdog',
  [int]$IntervalMinutes = 5,
  [string]$RunAsUser,
  [switch]$AsSystem = $true
)
$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path (Join-Path $PSScriptRoot '..') '..')).Path
$Wrapper = Join-Path $RepoRoot 'infra\allenco\run_api.ps1'
if (-not (Test-Path $Wrapper)) { throw "Wrapper not found: $Wrapper" }

# Action: run the watchdog under PowerShell — no profile, bypass execution
# policy so the unsigned .ps1 runs under the task.
$Action = New-ScheduledTaskAction `
  -Execute 'powershell.exe' `
  -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Wrapper`"" `
  -WorkingDirectory $RepoRoot

# Repeat every $IntervalMinutes, indefinitely, starting now.
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
  -RepetitionDuration ([TimeSpan]::MaxValue)

# StartWhenAvailable → catch up after a reboot/missed slot; no network
# requirement (the watchdog only touches the local uvicorn process); short
# execution cap since each check should return in seconds.
$Settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
  -MultipleInstances IgnoreNew

$Description = "Keeps the AllenCo Custom Action API (uvicorn) running behind IIS; checks every $IntervalMinutes min (runs infra/allenco/run_api.ps1)."
$Common = @{
  TaskName    = $TaskName
  Action      = $Action
  Trigger     = $Trigger
  Settings    = $Settings
  Description = $Description
  Force       = $true
}

# Registering a task (especially -Principal SYSTEM) needs an elevated shell.
# Fail fast with a clear message instead of the confusing raw CimException.
$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$IsElevated = (New-Object Security.Principal.WindowsPrincipal($CurrentIdentity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsElevated) {
  throw 'This script must run in an elevated PowerShell (Run as Administrator) to register a scheduled task.'
}

# Principal / Run As. SYSTEM is the default since the watchdog only needs
# local rights to the repo + .venv and to start/stop the uvicorn process.
# Register-ScheduledTask can raise its failure as a non-terminating CIM error
# even under $ErrorActionPreference='Stop', so force it to stop here explicitly.
if ($RunAsUser) {
  $Secure = Read-Host -AsSecureString "Password for $RunAsUser (stored by Task Scheduler; task runs whether the user is logged on or not)"
  $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  try { $Plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto($Bstr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr) }
  Register-ScheduledTask @Common -User $RunAsUser -Password $Plain -RunLevel Limited -ErrorAction Stop | Out-Null
}
else {
  $Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
  Register-ScheduledTask @Common -Principal $Principal -ErrorAction Stop | Out-Null
}

Write-Host ">> Registered task '$TaskName' (every $IntervalMinutes min)."
$Info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host ">> Next run:  $($Info.NextRunTime)"
Write-Host ">> Test now:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ">> Result:    (Get-ScheduledTaskInfo -TaskName '$TaskName').LastTaskResult   # 0 = OK"
Write-Host ">> Watchdog log: $RepoRoot\logs\watchdog.log"
