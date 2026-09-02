# ============================================================================
# Run the Allen & Co Glean indexer ONCE (PowerShell) — the wrapper the weekly
# Windows Task Scheduler task executes on the Managed Windows Instance.
#
# Thin by design: the RUN MODE lives in .env, not here. src/main.py calls
# load_dotenv(override=True), so .env WINS over shell/process env vars — setting
# GLEAN_ENABLE_INDEXING / GLEAN_FULL_REFRESH here would be silently ignored. This
# script only fixes PYTHONPATH (read by the interpreter before dotenv), runs the
# pipeline from the repo root, tees a per-run log, prunes old logs, and returns
# the indexer's exit code so Task Scheduler records it (0 = OK, non-zero = fail).
#
# Setup + the required .env: infra/allenco/SCHEDULED-INDEXING.md
#
# Usage:
#   ./infra/allenco/run-indexer.ps1                    # real run (mode per .env)
#   ./infra/allenco/run-indexer.ps1 -RetentionDays 30  # keep 30 days of logs
# ============================================================================
param(
  [string]$LogDir,
  [int]$RetentionDays = 90
)
$ErrorActionPreference = 'Stop'
# In PS 7.3+ a non-zero native exit can be turned into a terminating error; keep it
# off so we always reach the summary + `exit $exit` below (no-op on Windows PS 5.1).
$PSNativeCommandUseErrorActionPreference = $false

$RepoRoot = (Resolve-Path (Join-Path (Join-Path $PSScriptRoot '..') '..')).Path
$Python   = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
  throw ("Python venv not found at $Python. Create it first (see infra/allenco/DEV-ENVIRONMENT.md): " +
         "python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -e '.[dev]'")
}

if (-not $LogDir) { $LogDir = Join-Path $RepoRoot 'logs\scheduled' }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$logFile = Join-Path $LogDir "indexer-$stamp.log"

# PYTHONPATH must be a process env var — the interpreter reads it at startup, before
# main.py runs load_dotenv(). (The run mode stays in .env; see the header.)
$env:PYTHONPATH = Join-Path $RepoRoot 'src'

Write-Host ">> Running indexer: $Python -m main  (cwd=$RepoRoot)"
Write-Host ">> Logging to: $logFile"

Push-Location $RepoRoot
try {
  # Merge stderr into stdout (*>&1) and tee everything to the per-run log.
  & $Python -m main *>&1 | Tee-Object -FilePath $logFile
  $exit = $LASTEXITCODE
}
finally {
  Pop-Location
}

# Retention: drop per-run logs older than $RetentionDays (0 = keep all).
if ($RetentionDays -gt 0) {
  $cutoff = (Get-Date).AddDays(-$RetentionDays)
  Get-ChildItem -Path $LogDir -Filter 'indexer-*.log' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    Remove-Item -Force -ErrorAction SilentlyContinue
}

if ($exit -eq 0) {
  Write-Host ">> Indexer finished OK (exit 0). Log: $logFile"
}
else {
  Write-Warning (">> Indexer FAILED (exit $exit). If NOTIFICATIONS_ENABLED=true a Slack alert " +
                 "already fired. Log: $logFile")
}
exit $exit
