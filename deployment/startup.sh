#!/bin/bash


source /home/mediafusion/.local/share/virtualenvs/mediafusion-*/bin/activate
echo "Running Beanie migrations..."
pipenv run beanie migrate -uri "${MONGO_URI:-$mongo_uri}" -db mediafusion -p migrations/

echo "Starting FastAPI server..."
pipenv run gunicorn api.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:7860 --timeout 120 --max-requests 500 --max-requests-jitter 200
