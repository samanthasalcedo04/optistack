@echo off
title OptiStack HMI 3D Dashboard
echo ========================================================
echo  Iniciando OptiStack HMI 3D Dashboard...
echo  Accede desde tu navegador a: http://localhost:8000
echo ========================================================
call .venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
