#!/bin/bash
# Run API Service using its venv

cd "$(dirname "$0")/04_api"
./venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
