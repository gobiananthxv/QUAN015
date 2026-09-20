# Start the QMAFIB platform: API on :8000, dashboard on :5173.
# Windows.  macOS / Linux: use ./run.sh
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$py = 'backend\.venv\Scripts\python.exe'

if (-not (Test-Path $py)) {
    Write-Output 'No virtualenv found. Creating one...'
    python -m venv backend\.venv --system-site-packages
    & $py -m pip install -q -r backend\requirements.txt
}

if (-not (Test-Path 'frontend\node_modules')) {
    Write-Output 'Installing dashboard dependencies...'
    npm install --prefix frontend
}

# Refuse to start on an occupied port: uvicorn would fail to bind, exit quietly,
# and leave an older process serving stale code while both URLs still return 200.
foreach ($p in @(8000, 5173)) {
    $busy = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($busy) {
        Write-Error "Port $p is already in use. Stop the existing process first, or it will keep serving stale code."
        exit 1
    }
}

Write-Output 'API       -> http://localhost:8000  (docs at /docs)'
Write-Output 'Dashboard -> http://localhost:5173'
Write-Output ''

# --host 127.0.0.1 is uvicorn's default and is stated anyway: the security model
# in app/security.py assumes loopback-only, and an assumption that lives in a
# default is one nobody sees before overriding it. Serving the dashboard to a
# conference network should be a deliberate edit here, not a flag someone adds
# without reading what it exposes.
$api = Start-Process -PassThru -NoNewWindow -FilePath (Resolve-Path $py) `
    -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000','--reload' -WorkingDirectory 'backend'
try {
    npm run dev --prefix frontend
} finally {
    if (-not $api.HasExited) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
}
