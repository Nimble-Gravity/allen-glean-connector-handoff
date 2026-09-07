# ============================================================================
# Watchdog for the Allen & Co Custom Action API (Uvicorn) on the Managed
# Windows Instance. Schedule this (Task Scheduler, every few minutes) to make
# sure uvicorn is up on localhost:$port; IIS reverse-proxies HTTPS + the
# public hostname to it (ARR/URL Rewrite -> http://127.0.0.1:$port). IIS does
# not manage the Python process itself, hence this script.
#
# Thin by design: does not touch .env / run mode. It only checks whether a
# matching uvicorn.exe is alive and (re)starts it if not; a port already held
# by something else is treated as "investigate manually", not auto-killed.
#
# Register the watchdog task with infra/allenco/register-api-watchdog-task.ps1
# (run in an elevated PowerShell). See that script for options.
# ============================================================================

$RepoRoot = "C:\allen-glean-connector-handoff"
Set-Location $RepoRoot

# Ensure logs directory exists
$logsPath = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $logsPath | Out-Null

$watchdogLog = Join-Path $logsPath "watchdog.log"
function Write-Log($message) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp - $message" | Out-File -FilePath $watchdogLog -Append -Encoding utf8
}

# Trim a log file once it crosses $MaxBytes: keep one rotated copy (.old,
# overwritten each time) instead of letting it grow forever. Safe only for
# files nothing else currently has open — see call sites below.
$MaxLogBytes = 10MB
function Limit-LogSize($path) {
    if ((Test-Path $path) -and (Get-Item $path).Length -gt $MaxLogBytes) {
        Move-Item -Path $path -Destination "$path.old" -Force
    }
}

Limit-LogSize $watchdogLog

# Paths
$uvicornPath = Join-Path $RepoRoot ".venv\Scripts\uvicorn.exe"
$appDir = Join-Path $RepoRoot "allenco_custom_action"
$port = 8000

if (-not (Test-Path $uvicornPath)) {
    Write-Log "uvicorn.exe not found at $uvicornPath. Create the venv first (see infra/allenco/DEV-ENVIRONMENT.md)."
    return
}

# Is a uvicorn process for this app (on this port) already running?
$existingProcess = Get-CimInstance Win32_Process -Filter "Name = 'uvicorn.exe'" |
    Where-Object { $_.CommandLine -like "*main:app*" -and $_.CommandLine -like "*--port $port*" }

if ($existingProcess) {
    Write-Log "Uvicorn already running (PID $($existingProcess.ProcessId)). Nothing to do."
    return
}

# Is something else bound to the port? (stale/orphaned or a conflicting process)
$portInUse = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($portInUse) {
    $pids = ($portInUse.OwningProcess | Sort-Object -Unique) -join ", "
    Write-Log "Port $port is already in use by PID(s) $pids, but no matching uvicorn process was found. Skipping start - investigate manually."
    return
}

Write-Log "No running instance found. Starting AllenCo Custom Action API (Uvicorn)..."

# uvicorn isn't running (checked above), so nothing holds these files open —
# safe to rotate here, unlike while the process is live.
Limit-LogSize "$logsPath\uvicorn-$port.log"
Limit-LogSize "$logsPath\uvicorn-$port-error.log"

# Bind to localhost only: IIS (ARR/URL Rewrite) is the public-facing reverse
# proxy on this box and forwards to http://127.0.0.1:$port.
Start-Process `
    -FilePath $uvicornPath `
    -ArgumentList "main:app --host 127.0.0.1 --port $port" `
    -WorkingDirectory $appDir `
    -RedirectStandardOutput "$logsPath\uvicorn-$port.log" `
    -RedirectStandardError "$logsPath\uvicorn-$port-error.log" `
    -NoNewWindow

Write-Log "API process started. Check logs in $logsPath"
