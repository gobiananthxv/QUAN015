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

$api = Start-Process -PassThru -NoNewWindow -FilePath (Resolve-Path $py) `
    -ArgumentList '-m','uvicorn','app.main:app','--port','8000' -WorkingDirectory 'backend'
try {
    npm run dev --prefix frontend
} finally {
    if (-not $api.HasExited) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
}
