#!/usr/bin/env bash
# AetherHome Startup Script
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$PROJECT_ROOT/bin"
OLLAMA_PATH="$BIN_DIR/ollama"
VENV_DIR="$PROJECT_ROOT/venv"
OLLAMA_MODELS_DIR="$PROJECT_ROOT/.ollama/models"

# 1. Start Ollama in background if binary exists
if [ -f "$OLLAMA_PATH" ]; then
    echo "Starting local Ollama service..."
    export OLLAMA_HOST="127.0.0.1:11434"
    export OLLAMA_MODELS="$OLLAMA_MODELS_DIR"
    "$OLLAMA_PATH" serve &
    OLLAMA_PID=$!
else
    echo "Ollama engine is not pre-installed. You can install it on demand from the web dashboard."
fi

# 2. Start FastAPI Server
echo "Starting AetherHome API Server..."
cd "$PROJECT_ROOT"
source "$VENV_DIR/bin/activate"

# Run python backend
python3 backend/main.py &
BACKEND_PID=$!

# Automatically open browser
sleep 2
if command -v xdg-open &> /dev/null; then
    xdg-open "http://localhost:8000" &> /dev/null || true
fi

# Keep script running and handle termination signals
cleanup() {
    echo "Shutting down services..."
    kill $BACKEND_PID 2>/dev/null || true
    if [ ! -z "$OLLAMA_PID" ]; then
        kill $OLLAMA_PID 2>/dev/null || true
    fi
    exit 0
}

trap cleanup SIGINT SIGTERM

wait
