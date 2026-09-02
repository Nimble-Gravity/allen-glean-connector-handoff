# ============================================================================
# Register (or update) the WEEKLY Windows Task Scheduler task that runs the
# Allen & Co Glean indexer on the Managed Windows Instance.
#
# Idempotent: re-running updates the existing task (-Force). Trigger times are
# LOCAL to the VM (unlike the Container Apps Job cron, which is UTC).
#
# With DB_AUTH_MODE=msi the database identity comes from the VM's managed identity
# (via IMDS), NOT the task's Run As token — so the Run As account only needs local
# rights to the repo and .venv. Use a service account (-RunAsUser) or SYSTEM
# (-AsSystem).
#
# Full runbook + the required .env: infra/allenco/SCHEDULED-INDEXING.md
#
# Usage (run in an ELEVATED PowerShell):
#   ./infra/allenco/register-scheduled-task.ps1 -AsSystem
#   ./infra/allenco/register-scheduled-task.ps1 -RunAsUser 'ALLENCO\svc-glean' -DayOfWeek Sunday -At 02:00
# ============================================================================
param(
  [string]$TaskName = 'AllenCo-Glean-Indexer-Weekly',
  [ValidateSet('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')]
  [string]$DayOfWeek = 'Sunday',
  [string]$At = '02:00',
  [string]$RunAsUser,
  [switch]$AsSystem
)
$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path (Join-Path $PSScriptRoot '..') '..')).Path
$Wrapper = Join-Path $RepoRoot 'infra\allenco\run-indexer.ps1'
if (-not (Test-Path $Wrapper)) { throw "Wrapper not found: $Wrapper" }

# Action: run the thin wrapper under PowerShell — no profile, bypass execution
# policy so the unsigned .ps1 runs under the task.
$Action = New-ScheduledTaskAction `
  -Execute 'powershell.exe' `
  -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Wrapper`"" `
  -WorkingDirectory $RepoRoot

$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $At

# StartWhenAvailable → catch a missed weekly slot (VM asleep); RunOnlyIfNetworkAvailable
# → don't fire without a network path to the MI / Glean; 6h cap as a safety net.
$Settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -RunOnlyIfNetworkAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Hours 6)

$Description = 'Weekly Allen & Co -> Glean full-refresh index (runs src/main.py via infra/allenco/run-indexer.ps1).'
$Common = @{
  TaskName    = $TaskName
  Action      = $Action
  Trigger     = $Trigger
  Settings    = $Settings
  Description  = $Description
  Force       = $true
}

# Principal / Run As. msi decouples the DB identity from this account (see header),
# so a low-privilege service account or SYSTEM is fine.
if ($AsSystem) {
  $Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
  Register-ScheduledTask @Common -Principal $Principal | Out-Null
}
elseif ($RunAsUser) {
  # -User/-Password on Register-ScheduledTask stores the password and sets logon
  # type = Password ("run whether user is logged on or not").
  $Secure = Read-Host -AsSecureString "Password for $RunAsUser (stored by Task Scheduler; task runs whether the user is logged on or not)"
  $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  try { $Plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto($Bstr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr) }
  Register-ScheduledTask @Common -User $RunAsUser -Password $Plain -RunLevel Limited | Out-Null
}
else {
  throw 'Specify -AsSystem or -RunAsUser <DOMAIN\account>. With msi the account only needs local rights to the repo + .venv (the DB identity comes from the VM managed identity).'
}

Write-Host ">> Registered task '$TaskName' (weekly $DayOfWeek $At, VM local time)."
$Info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host ">> Next run:  $($Info.NextRunTime)"
Write-Host ">> Test now:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ">> Result:    (Get-ScheduledTaskInfo -TaskName '$TaskName').LastTaskResult   # 0 = OK"
