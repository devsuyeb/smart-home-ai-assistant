#!/usr/bin/env bash
# AetherHome Smart AI Assistant Installer
# Packages everything locally (Ollama, models, and Python dependencies)

set -e

# Setup absolute paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BIN_DIR="$PROJECT_ROOT/bin"
OLLAMA_PATH="$BIN_DIR/ollama"
VENV_DIR="$PROJECT_ROOT/venv"
OLLAMA_MODELS_DIR="$PROJECT_ROOT/.ollama/models"

echo "=== AetherHome Linux Installer ==="
echo "Project Root: $PROJECT_ROOT"
echo "Architecture: $(uname -m)"

# 1. Install system prerequisites if possible (inform user if password needed)
echo "--------------------------------------------------"
echo "Step 1: Checking system packages..."
if ! command -v tar &> /dev/null || ! command -v zstd &> /dev/null; then
    echo "[!] Missing core compression tools (tar/zstd)."
    echo "Please run: sudo apt install -y tar zstd"
    exit 1
fi
echo "[+] System package requirements met."

# 2. Setup Ollama local binary
echo "--------------------------------------------------"
echo "Step 2: Setting up Ollama local inference engine..."
mkdir -p "$BIN_DIR"
if [ ! -f "$OLLAMA_PATH" ]; then
    echo "Downloading Ollama binary for ARM64..."
    TEMP_TAR="/tmp/ollama-linux-arm64.tar.zst"
    curl -L "https://ollama.com/download/ollama-linux-arm64.tar.zst" -o "$TEMP_TAR"
    
    echo "Extracting Ollama into binary folder..."
    tar --zstd -xf "$TEMP_TAR" -C "$PROJECT_ROOT"
    rm -f "$TEMP_TAR"
    echo "[+] Ollama binary installed at $OLLAMA_PATH"
else
    echo "[+] Ollama binary already present."
fi

# 3. Setup local python virtual environment
echo "--------------------------------------------------"
echo "Step 3: Creating Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "[+] Virtual environment created."
else
    echo "[+] Virtual environment already exists."
fi

echo "Installing python packages..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$PROJECT_ROOT/requirements.txt"
echo "[+] Python dependencies installed."

# 4. Pre-download Default AI Model (TinyLlama 1.1B)
echo "--------------------------------------------------"
echo "Step 4: Pre-fetching default local AI model (TinyLlama 1.1B)..."
mkdir -p "$OLLAMA_MODELS_DIR"

# Launch Ollama temporarily to pull the model
echo "Starting local Ollama server momentarily..."
OLLAMA_HOST="127.0.0.1:11434" OLLAMA_MODELS="$OLLAMA_MODELS_DIR" "$OLLAMA_PATH" serve &
OLLAMA_PID=$!

# Wait for Ollama to spin up
echo "Waiting for Ollama to respond..."
for i in {1..15}; do
    if curl -s http://127.0.0.1:11434/api/tags &> /dev/null; then
        echo "[+] Ollama server is responding."
        break
    fi
    sleep 1
done

# Pull TinyLlama
echo "Downloading TinyLlama 1.1B (~600MB) directly into local cache..."
OLLAMA_HOST="127.0.0.1:11434" "$OLLAMA_PATH" pull tinyllama:1.1b

# Stop temporary Ollama server
echo "Stopping temporary server..."
kill $OLLAMA_PID
wait $OLLAMA_PID 2>/dev/null || true
echo "[+] Default model (TinyLlama 1.1B) pre-loaded."

# 5. Create Desktop Entry & Launcher
echo "--------------------------------------------------"
echo "Step 5: Creating application launcher..."

# Launcher Script
LAUNCHER_SCRIPT="$PROJECT_ROOT/aetherhome.sh"
cat << 'EOF' > "$LAUNCHER_SCRIPT"
#!/usr/bin/env bash
# AetherHome Startup Script
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$PROJECT_ROOT/bin"
OLLAMA_PATH="$BIN_DIR/ollama"
VENV_DIR="$PROJECT_ROOT/venv"
OLLAMA_MODELS_DIR="$PROJECT_ROOT/.ollama/models"

# 1. Start Ollama in background
echo "Starting local Ollama service..."
export OLLAMA_HOST="127.0.0.1:11434"
export OLLAMA_MODELS="$OLLAMA_MODELS_DIR"
"$OLLAMA_PATH" serve &
OLLAMA_PID=$!

# 2. Start FastAPI Server
echo "Starting AetherHome API Server..."
cd "$PROJECT_ROOT"
source "$VENV_DIR/bin/activate"

# Set default active model to tinyllama
export GEMINI_API_KEY=""

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
    kill $OLLAMA_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

wait
EOF

chmod +x "$LAUNCHER_SCRIPT"
echo "[+] Created startup script at $LAUNCHER_SCRIPT"

# Linux Desktop Shortcut Integration (.desktop file)
DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"
DESKTOP_FILE="$DESKTOP_DIR/aetherhome.desktop"

cat << EOF > "$DESKTOP_FILE"
[Desktop Entry]
Version=1.0
Type=Application
Name=AetherHome
Comment=Smart AI Home Assistant Hub
Exec=$LAUNCHER_SCRIPT
Icon=utilities-system-monitor
Terminal=true
Categories=Utility;Development;
EOF

echo "[+] Registered AetherHome in Linux system app menu: $DESKTOP_FILE"
echo "--------------------------------------------------"
echo "=== INSTALLATION COMPLETED SUCCESSFULLY ==="
echo "You can now start AetherHome in two ways:"
echo "1. Run: ./aetherhome.sh from this folder"
echo "2. Find 'AetherHome' in your Linux applications list/app menu!"
echo "==========================================="
