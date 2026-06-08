#!/bin/bash
set -e
echo "Creating database tables..."
uv run python -m app.database.connection
echo "Running pipeline..."
uv run python main.py 24 10
