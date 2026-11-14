#!/usr/bin/env bash
# Slab Thickness Analyzer - macOS/Linux launcher
set -e
cd "$(dirname "$0")"
if [ ! -f .venv/installed.ok ]; then
  echo "[1/2] Creating virtual environment and installing packages - first run only, 1-3 minutes..."
  [ -x .venv/bin/python ] || python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv/installed.ok
fi
# Skip Streamlit's first-run email prompt
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
  mkdir -p "$HOME/.streamlit"
  printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi
echo "[2/2] Starting Slab Thickness Analyzer: http://localhost:8501 (stop: Ctrl+C)"
exec .venv/bin/python -m streamlit run app.py "$@"
