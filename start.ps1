<#
.SYNOPSIS
    Second Brain AI - one-click local start (checks, DB copy, migrations, CSS, tests, server).

.DESCRIPTION
    Runs, in order, each step with a header and a coloured OK / FAIL / WARN status:
      1. environment checks (venv python, node/npx, Python version, .env / AI variables)
      2. local SQLite copy ai_manager\audit_copy_db.sqlite3 (created from db.sqlite3 only if missing)
      3. optional dependency install (-Install)
      4. manage.py check + migrate (settings_local, never the production DB)
      5. Tailwind CSS build (npm run build)
      6. tests: fast by default, -FullTests = everything incl. Playwright, -SkipTests = none
      7. runserver on -Port and open the browser once the server answers
    Every run is logged to logs\runs\run_YYYY-MM-DD_HH-mm-ss.log (last 30 kept) and
    summarised in logs\runs\history.csv. The contents of .env are never read or printed.

.PARAMETER Install     pip install -r requirements.txt -r requirements-dev.txt and npm install
.PARAMETER FullTests   run the whole test suite (unit + integration + e2e + responsive)
.PARAMETER SkipTests   do not run tests
.PARAMETER Force       start the server even if tests failed (and skip the -Docker confirmation)
.PARAMETER Port        port for runserver (default 8000)
.PARAMETER Watch       also start "npm run dev" (Tailwind watch) in a separate window
.PARAMETER Tunnel      also start "cloudflared tunnel --url http://127.0.0.1:<Port>" in a separate window
.PARAMETER Docker      instead of the local mode run "docker compose up --build" (PRODUCTION configuration!)
.PARAMETER NoBrowser   do not open the browser
.PARAMETER NoServer    stop after the checks/tests (useful for CI or a quick health check)

.EXAMPLE
    .\start.bat                      # fast tests, then server on :8000
    .\start.bat -SkipTests -Port 8080
    .\start.bat -FullTests -Watch
#>
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$FullTests,
    [switch]$SkipTests,
    [switch]$Force,
    [ValidateRange(1, 65535)][int]$Port = 8000,
    [switch]$Watch,
    [switch]$Tunnel,
    [switch]$Docker,
    [switch]$NoBrowser,
    [switch]$NoServer
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$App = Join-Path $Root 'ai_manager'
$Python = Join-Path $Root 'venv\Scripts\python.exe'
$RunsDir = Join-Path $Root 'logs\runs'
$Stamp = Get-Date -Format 'yyyy-MM-dd_HH-mm-ss'
$LogFile = Join-Path $RunsDir "run_$Stamp.log"
$HistoryFile = Join-Path $RunsDir 'history.csv'
$KeepLogs = 30

$script:Steps = New-Object System.Collections.Generic.List[object]
$script:TestsPassed = ''
$script:TestsFailed = ''
$script:Result = 'OK'
$script:RunStart = Get-Date

New-Item -ItemType Directory -Force -Path $RunsDir | Out-Null
try { Start-Transcript -Path $LogFile -Force | Out-Null } catch { Write-Host "WARN: could not start transcript: $_" -ForegroundColor Yellow }

# ---------------------------------------------------------------- helpers
function Write-Header([string]$Text) {
    Write-Host ''
    Write-Host ('=' * 70) -ForegroundColor DarkCyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ('=' * 70) -ForegroundColor DarkCyan
}

function Write-Status([string]$Status, [string]$Text) {
    $colour = switch ($Status) { 'OK' { 'Green' } 'FAIL' { 'Red' } 'WARN' { 'Yellow' } 'SKIP' { 'DarkGray' } default { 'White' } }
    Write-Host ("  [{0,-4}] {1}" -f $Status, $Text) -ForegroundColor $colour
}

# Run a native command through cmd so stdout+stderr reach the console AND the transcript.
function Invoke-Native([string]$CommandLine, [string]$WorkDir = $Root, [string]$TeeVariable = '') {
    Push-Location $WorkDir
    try {
        if ($TeeVariable) {
            cmd /c "$CommandLine 2>&1" | Tee-Object -Variable captured | Out-Host
            Set-Variable -Name $TeeVariable -Value $captured -Scope Script
        } else {
            cmd /c "$CommandLine 2>&1" | Out-Host
        }
        return $LASTEXITCODE
    } finally {
        Pop-Location
    }
}

function Invoke-Step([string]$Name, [scriptblock]$Body) {
    Write-Header $Name
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $status = 'OK'
    $note = ''
    try {
        $out = & $Body
        if ($out -is [string] -and $out -in @('WARN', 'SKIP', 'FAIL')) { $status = $out }
    } catch {
        $status = 'FAIL'
        $note = $_.Exception.Message
        Write-Status 'FAIL' $note
    }
    $watch.Stop()
    $seconds = [math]::Round($watch.Elapsed.TotalSeconds, 1)
    Write-Host ("  -> {0} in {1}s" -f $status, $seconds) -ForegroundColor DarkGray
    $script:Steps.Add([pscustomobject]@{ Step = $Name; Status = $status; Seconds = $seconds; Note = $note })
    return $status
}

function Remove-OldLogs {
    $logs = Get-ChildItem -Path $RunsDir -Filter 'run_*.log' -ErrorAction SilentlyContinue | Sort-Object Name -Descending
    if ($logs.Count -gt $KeepLogs) {
        $logs | Select-Object -Skip $KeepLogs | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }
    }
}

function Write-Summary {
    $total = [math]::Round(((Get-Date) - $script:RunStart).TotalSeconds, 1)
    Write-Header 'Summary'
    foreach ($s in $script:Steps) { Write-Status $s.Status ("{0}  ({1}s){2}" -f $s.Step, $s.Seconds, $(if ($s.Note) { " - $($s.Note)" } else { '' })) }
    if ($script:TestsPassed -ne '' -or $script:TestsFailed -ne '') {
        Write-Host ("  Tests: {0} passed, {1} failed" -f $(if ($script:TestsPassed) { $script:TestsPassed } else { 0 }), $(if ($script:TestsFailed) { $script:TestsFailed } else { 0 }))
    }
    $colour = if ($script:Result -eq 'OK') { 'Green' } else { 'Red' }
    Write-Host ("  RESULT: {0}   (total {1}s before server start)" -f $script:Result, $total) -ForegroundColor $colour
    Write-Host "  Log: $LogFile" -ForegroundColor Cyan
}

function Write-History {
    if (-not (Test-Path $HistoryFile)) {
        'date,branch,commit,mode,tests_passed,tests_failed,result' | Set-Content -Path $HistoryFile -Encoding UTF8
    }
    $mode = if ($Docker) { 'docker' } elseif ($SkipTests) { 'skip-tests' } elseif ($FullTests) { 'full-tests' } else { 'fast-tests' }
    ('{0},{1},{2},{3},{4},{5},{6}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $script:Branch, $script:Commit, $mode,
        $script:TestsPassed, $script:TestsFailed, $script:Result) | Add-Content -Path $HistoryFile -Encoding UTF8
}

function Stop-Run([int]$Code) {
    if ($Code -ne 0) { $script:Result = 'FAIL' }
    Write-Summary
    Write-History
    Remove-OldLogs
    try { Stop-Transcript | Out-Null } catch {}
    exit $Code
}

# ---------------------------------------------------------------- run info
$script:Branch = (git -C $Root rev-parse --abbrev-ref HEAD 2>$null)
$script:Commit = (git -C $Root rev-parse --short HEAD 2>$null)
if (-not $script:Branch) { $script:Branch = 'unknown' }
if (-not $script:Commit) { $script:Commit = 'unknown' }
Write-Header 'Second Brain AI - start'
Write-Host "  Time:       $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "  Git:        $($script:Branch) @ $($script:Commit)"
$paramText = ($PSBoundParameters.GetEnumerator() | ForEach-Object { "-$($_.Key) $($_.Value)" }) -join ' '
Write-Host "  Parameters: $(if ($paramText) { $paramText } else { '(defaults)' })  Port=$Port"
Write-Host "  Log file:   $LogFile"

if ($FullTests -and $SkipTests) {
    Write-Status 'FAIL' '-FullTests and -SkipTests cannot be combined.'
    Stop-Run 2
}

# ---------------------------------------------------------------- 1. environment
$envStatus = Invoke-Step '1. Environment checks' {
    $warn = $false
    if (-not (Test-Path $Python)) { throw "venv not found: $Python (create it: python -m venv venv)" }
    $pyVersion = (& $Python --version 2>&1 | Out-String).Trim()
    Write-Status 'OK' "Python: $pyVersion ($Python)"
    if ($pyVersion -match 'Python (\d+)\.(\d+)') {
        if ([int]$Matches[1] -lt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 10)) { throw "Python 3.10+ required, found $pyVersion" }
    }
    foreach ($tool in @('node', 'npx', 'git')) {
        $cmd = Get-Command $tool -ErrorAction SilentlyContinue
        if ($cmd) { Write-Status 'OK' "$tool found ($($cmd.Source))" }
        elseif ($tool -eq 'git') { Write-Status 'WARN' 'git not found (commit info unavailable)'; $warn = $true }
        else { throw "$tool not found - install Node.js (needed for the Tailwind build)" }
    }
    # Only the existence of .env is checked - its contents are never read or shown.
    $envFile = Join-Path $Root '.env'
    if (Test-Path $envFile) { Write-Status 'OK' '.env present (contents not read)' }
    else { Write-Status 'WARN' '.env not found - a development SECRET_KEY is used; AI keys must come from the environment'; $warn = $true }
    foreach ($name in @('GEMINI_API_KEY', 'OLLAMA_HOST')) {
        if ([Environment]::GetEnvironmentVariable($name)) { Write-Status 'OK' "$name is set in the environment" }
        else {
            $hint = if (Test-Path $envFile) { ' (may still be defined in .env)' } else { '' }
            Write-Status 'WARN' "$name is not set in the environment$hint"
            $warn = $true
        }
    }
    if ($Docker) {
        if (Get-Command docker -ErrorAction SilentlyContinue) { Write-Status 'OK' 'docker found' } else { throw 'docker not found' }
    }
    if ($warn) { 'WARN' }
}
if ($envStatus -eq 'FAIL') { Stop-Run 1 }

# ---------------------------------------------------------------- Docker mode
if ($Docker) {
    Write-Header 'Docker mode - PRODUCTION configuration'
    Write-Status 'WARN' 'docker compose uses docker-compose.yml: PostgreSQL volume, gunicorn, cloudflared - this is the production setup.'
    Write-Status 'WARN' 'It does not use the local SQLite copy. Local tests/migrations are skipped in this mode.'
    if (-not $Force) {
        $answer = Read-Host '  Type YES to continue'
        if ($answer -ne 'YES') { Write-Status 'SKIP' 'Cancelled.'; Stop-Run 0 }
    }
    $script:Result = 'OK'
    Write-Summary
    Write-History
    Remove-OldLogs
    $code = Invoke-Native 'docker compose up --build' $Root
    try { Stop-Transcript | Out-Null } catch {}
    exit $code
}

# ---------------------------------------------------------------- 2. DB copy
$dbStatus = Invoke-Step '2. Local database copy (SQLite)' {
    $copy = Join-Path $App 'audit_copy_db.sqlite3'
    $source = Join-Path $App 'db.sqlite3'
    if ($env:AUDIT_SQLITE_PATH) { Write-Status 'OK' "AUDIT_SQLITE_PATH set: $env:AUDIT_SQLITE_PATH"; return }
    if (Test-Path $copy) { Write-Status 'OK' "Copy exists, not touched: $copy"; return }
    if (Test-Path $source) {
        Copy-Item -LiteralPath $source -Destination $copy
        Write-Status 'OK' "Created $copy from db.sqlite3 (the original is never modified)"
    } else {
        Write-Status 'WARN' 'db.sqlite3 not found - migrate will create an empty local database'
        'WARN'
    }
}
if ($dbStatus -eq 'FAIL') { Stop-Run 1 }

# ---------------------------------------------------------------- 3. install
if ($Install) {
    $installStatus = Invoke-Step '3. Install dependencies' {
        $code = Invoke-Native "`"$Python`" -m pip install -r requirements.txt -r requirements-dev.txt" $Root
        if ($code -ne 0) { throw "pip install failed (exit $code)" }
        $code = Invoke-Native 'npm install' $App
        if ($code -ne 0) { throw "npm install failed (exit $code)" }
        Write-Status 'OK' 'Python and Node dependencies installed'
    }
    if ($installStatus -eq 'FAIL') { Stop-Run 1 }
} else {
    $script:Steps.Add([pscustomobject]@{ Step = '3. Install dependencies'; Status = 'SKIP'; Seconds = 0; Note = 'use -Install' })
}

# ---------------------------------------------------------------- 4. check + migrate
$djangoStatus = Invoke-Step '4. Django check + migrate (settings_local)' {
    $code = Invoke-Native "`"$Python`" manage.py check --settings=ai_manager.settings_local" $App
    if ($code -ne 0) { throw "manage.py check failed (exit $code)" }
    $code = Invoke-Native "`"$Python`" manage.py migrate --settings=ai_manager.settings_local" $App
    if ($code -ne 0) { throw "migrate failed (exit $code)" }
    Write-Status 'OK' 'System check passed, migrations applied to the local copy'
}
if ($djangoStatus -eq 'FAIL') { Stop-Run 1 }

# ---------------------------------------------------------------- 5. CSS
$cssStatus = Invoke-Step '5. Build CSS (Tailwind)' {
    $code = Invoke-Native 'npm run build' $App
    if ($code -ne 0) { throw "npm run build failed (exit $code)" }
    Write-Status 'OK' 'static/css/styles.css rebuilt'
}
if ($cssStatus -eq 'FAIL') { Stop-Run 1 }

# ---------------------------------------------------------------- 6. tests
if ($SkipTests) {
    $script:Steps.Add([pscustomobject]@{ Step = '6. Tests'; Status = 'SKIP'; Seconds = 0; Note = '-SkipTests' })
    Write-Header '6. Tests'
    Write-Status 'SKIP' 'Tests skipped (-SkipTests)'
} else {
    $label = if ($FullTests) { '6. Tests (full: unit + e2e + responsive)' } else { '6. Tests (fast: not e2e and not responsive)' }
    $testStatus = Invoke-Step $label {
        $marker = if ($FullTests) { '' } else { ' -m "not e2e and not responsive"' }
        $code = Invoke-Native "`"$Python`" -m pytest -q -p no:warnings$marker" $App 'TestOutput'
        $summary = ($script:TestOutput | Where-Object { "$_" -match '\d+ (passed|failed)' } | Select-Object -Last 1)
        if ($summary -match '(\d+) passed') { $script:TestsPassed = $Matches[1] } else { $script:TestsPassed = '0' }
        if ($summary -match '(\d+) failed') { $script:TestsFailed = $Matches[1] } else { $script:TestsFailed = '0' }
        if ($summary -match '(\d+) error') { $script:TestsFailed = [string]([int]$script:TestsFailed + [int]$Matches[1]) }
        if ($code -ne 0) { throw "tests failed: $("$summary".Trim())" }
        Write-Status 'OK' "$("$summary".Trim())"
    }
    if ($testStatus -eq 'FAIL') {
        if (-not $Force) {
            Write-Host ''
            Write-Host '  Tests failed - the server was NOT started. Details are in the log:' -ForegroundColor Red
            Write-Host "  $LogFile" -ForegroundColor Red
            Write-Host '  Use -Force to start the server anyway, or -SkipTests to skip the tests.' -ForegroundColor Yellow
            Stop-Run 1
        }
        Write-Status 'WARN' 'Tests failed, starting anyway because of -Force'
        $script:Result = 'FAIL'
    }
}

if ($NoServer) {
    Stop-Run $(if ($script:Result -eq 'OK') { 0 } else { 1 })
}

# ---------------------------------------------------------------- 7. extras + server
Write-Header "7. Server on http://127.0.0.1:$Port"
if ($Watch) {
    Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$App'; `$host.UI.RawUI.WindowTitle = 'Tailwind watch'; npm run dev" | Out-Null
    Write-Status 'OK' 'Tailwind watch started in a separate window'
}
if ($Tunnel) {
    $cloudflared = Join-Path $App 'cloudflared.exe'
    if (-not (Test-Path $cloudflared)) {
        $found = Get-Command cloudflared -ErrorAction SilentlyContinue
        $cloudflared = if ($found) { $found.Source } else { '' }
    }
    if ($cloudflared) {
        Start-Process powershell -ArgumentList '-NoExit', '-Command', "`$host.UI.RawUI.WindowTitle = 'Cloudflare tunnel'; & '$cloudflared' tunnel --url http://127.0.0.1:$Port" | Out-Null
        Write-Status 'OK' 'cloudflared tunnel started in a separate window'
    } else {
        Write-Status 'WARN' 'cloudflared not found (neither ai_manager\cloudflared.exe nor on PATH) - tunnel skipped'
    }
}

$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Status 'FAIL' "Port $Port is already in use - choose another one with -Port"
    Stop-Run 1
}

# Summary + history are written now: the server keeps running until Ctrl+C.
Write-Summary
Write-History
Remove-OldLogs

if (-not $NoBrowser) {
    # Open the browser in the background as soon as the server answers.
    Start-Job -ArgumentList $Port -ScriptBlock {
        param($p)
        for ($i = 0; $i -lt 120; $i++) {
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:$p/login/" -UseBasicParsing -TimeoutSec 2
                if ($r.StatusCode -lt 500) { Start-Process "http://127.0.0.1:$p"; return }
            } catch {}
            Start-Sleep -Milliseconds 500
        }
    } | Out-Null
}

Write-Host "  Starting Django (Ctrl+C to stop) ..." -ForegroundColor Cyan
try {
    $code = Invoke-Native "`"$Python`" manage.py runserver 127.0.0.1:$Port --settings=ai_manager.settings_local" $App
} finally {
    Get-Job -ErrorAction SilentlyContinue | Remove-Job -Force -ErrorAction SilentlyContinue
    Write-Host "  Server stopped. Log: $LogFile" -ForegroundColor Cyan
    try { Stop-Transcript | Out-Null } catch {}
}
exit $code
