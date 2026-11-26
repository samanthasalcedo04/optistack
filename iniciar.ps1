Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " Iniciando OptiStack HMI 3D Dashboard... " -ForegroundColor Green
Write-Host " Accede desde tu navegador a: http://localhost:8000 " -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Cyan

& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
