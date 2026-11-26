#!/bin/bash
# Script de inicio para Azure App Service (Linux - Python 3.11)
gunicorn -w 2 -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:${PORT:-8000} --timeout 120
