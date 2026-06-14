#!/bin/bash
set -e

echo "[start] Starting uvicorn on 127.0.0.1:8000..."
python main.py --serve --port 8000 &
UVICORN_PID=$!

# Wait for uvicorn to be ready
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:8000/api/health > /dev/null 2>&1; then
        echo "[start] Uvicorn ready"
        break
    fi
    sleep 1
done

echo "[start] Starting nginx on 0.0.0.0:8080..."
exec nginx -g "daemon off;"
