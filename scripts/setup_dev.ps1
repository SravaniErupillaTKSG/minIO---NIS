# DMS local dev bootstrap — run once after cloning
# Usage: .\scripts\setup_dev.ps1

Write-Host "=== DMS Local Dev Setup ===" -ForegroundColor Cyan

# 1. Copy .env if missing
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[OK] .env created from .env.example" -ForegroundColor Green
} else {
    Write-Host "[SKIP] .env already exists" -ForegroundColor Yellow
}

# 2. Create Python virtual environment
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
    Write-Host "[OK] .venv created" -ForegroundColor Green
} else {
    Write-Host "[SKIP] .venv already exists" -ForegroundColor Yellow
}

# 3. Install dependencies
Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
& .venv\Scripts\pip install -r requirements.txt
Write-Host "[OK] Dependencies installed" -ForegroundColor Green

# 4. Start infrastructure
Write-Host "Starting MinIO via Docker Compose..." -ForegroundColor Cyan
docker compose up -d minio minio-init
Write-Host "[OK] MinIO started" -ForegroundColor Green

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Green
Write-Host "MinIO Console : http://localhost:9001  (minioadmin / minioadmin123)" -ForegroundColor White
Write-Host "FastAPI Docs  : http://localhost:8000/docs  (start app first)" -ForegroundColor White
Write-Host ""
Write-Host "To start the app:" -ForegroundColor White
Write-Host "  .venv\Scripts\activate" -ForegroundColor Gray
Write-Host "  uvicorn app.main:app --reload" -ForegroundColor Gray
