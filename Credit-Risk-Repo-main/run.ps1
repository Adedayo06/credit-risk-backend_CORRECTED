# Starts BOTH backend services the frontend needs:
#   - Model API      -> http://localhost:8000  (POST /score, /metrics, /health)
#   - Batch API      -> http://localhost:8001  (batch scoring + score reports)
#
# The batch API calls the model API over HTTP, so BOTH must be running or
# batch scoring will fail with "unable to connect". Run this from the repo root:
#   powershell -ExecutionPolicy Bypass -File .\run.ps1
#
# Press Ctrl+C in each window to stop.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# Prefer the project's virtual environment if one exists.
$venvPython = Join-Path (Split-Path $root -Parent) ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $python = $venvPython
} else {
    $python = "python"
}

Write-Host "Using Python: $python"
Write-Host "Starting Model API on :8000 and Batch API on :8001 ..."

# Model API (must run from credit-risk-api so it can load model/... )
Start-Process -FilePath $python `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000" `
    -WorkingDirectory (Join-Path $root "credit-risk-api")

# Batch API (runs from batch-api)
Start-Process -FilePath $python `
    -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001" `
    -WorkingDirectory (Join-Path $root "batch-api")

Write-Host "Both services launched in separate windows. Now run the frontend (npm run dev)."
