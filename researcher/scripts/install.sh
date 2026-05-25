#!/usr/bin/env bash
# THE RESEARCHER — Linux install script
# Run from the project root: bash scripts/install.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CURRENT_USER="$(whoami)"
SERVICE_NAME="researcher"
MIN_PYTHON="3.11"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()     { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

echo ""
echo -e "${CYAN}╔══════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     THE RESEARCHER  —  Linux Setup   ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════╝${NC}"
echo ""

# ── 1. OS check ───────────────────────────────────────────────────────────────
[[ "$(uname -s)" == "Linux" ]] || die "This script is for Linux only."

# ── 2. Python version check ───────────────────────────────────────────────────
PYTHON_BIN=""
for candidate in python3.11 python3.12 python3.13 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver="$($candidate -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        major="${ver%%.*}"; minor="${ver##*.}"
        if [[ "$major" -ge 3 && "$minor" -ge 11 ]]; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done
[[ -n "$PYTHON_BIN" ]] || die "Python $MIN_PYTHON+ required. Install with: sudo apt install python3.11"
success "Python: $($PYTHON_BIN --version)"

# ── 3. Virtual environment ────────────────────────────────────────────────────
info "Creating virtualenv at $PROJECT_DIR/venv ..."
"$PYTHON_BIN" -m venv "$PROJECT_DIR/venv"
source "$PROJECT_DIR/venv/bin/activate"
pip install --quiet --upgrade pip
success "Virtualenv ready"

# ── 4. Dependencies ───────────────────────────────────────────────────────────
info "Installing dependencies ..."
pip install --quiet -r "$PROJECT_DIR/requirements.txt"
success "Dependencies installed"

# ── 5. Environment file ───────────────────────────────────────────────────────
if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    warn ".env created from .env.example — fill in your API credentials before starting"
else
    success ".env already exists — skipping"
fi

# ── 6. Ollama check ───────────────────────────────────────────────────────────
echo ""
if command -v ollama &>/dev/null; then
    success "Ollama is installed: $(ollama --version 2>/dev/null || echo 'version unknown')"
    # Check for GPU
    if command -v nvidia-smi &>/dev/null; then
        GPU="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"
        success "NVIDIA GPU detected: $GPU — Ollama will use it automatically"
    else
        warn "No NVIDIA GPU detected — Ollama will run on CPU (slower)"
    fi
else
    warn "Ollama not found. Installing now..."
    curl -fsSL https://ollama.com/install.sh | sh
    success "Ollama installed"
fi

# ── 7. Pull recommended model ─────────────────────────────────────────────────
echo ""
info "Checking for recommended model (qwen2.5:7b) ..."
if ollama list 2>/dev/null | grep -q "qwen2.5:7b"; then
    success "qwen2.5:7b already pulled"
else
    read -rp "Pull qwen2.5:7b now? It's ~4.7 GB and works great on your GPU [Y/n]: " pull_model
    if [[ "${pull_model:-Y}" =~ ^[Yy]$ ]]; then
        ollama pull qwen2.5:7b
        success "qwen2.5:7b ready"
        # Update .env to use qwen2.5:7b
        sed -i 's/^RESEARCHER_MODEL=.*/RESEARCHER_MODEL=qwen2.5:7b/' "$PROJECT_DIR/.env"
    else
        info "Skipping model pull — update RESEARCHER_MODEL in .env when ready"
    fi
fi

# ── 8. Systemd service (optional) ─────────────────────────────────────────────
echo ""
read -rp "Install systemd service (auto-start on boot)? [Y/n]: " install_service
if [[ "${install_service:-Y}" =~ ^[Yy]$ ]]; then
    if [[ "$EUID" -ne 0 ]]; then
        warn "Systemd install needs sudo — re-running that step with sudo ..."
        sudo bash -c "
            SERVICE_FILE='$PROJECT_DIR/researcher.service'
            DEST='/etc/systemd/system/researcher.service'
            sed -e 's|__USER__|$CURRENT_USER|g' \
                -e 's|__PROJECT_DIR__|$PROJECT_DIR|g' \
                \"\$SERVICE_FILE\" > \"\$DEST\"
            systemctl daemon-reload
            systemctl enable researcher
            echo 'Service installed and enabled'
        "
        success "Systemd service installed — run 'make start' or 'sudo systemctl start researcher'"
    else
        SERVICE_FILE="$PROJECT_DIR/researcher.service"
        DEST="/etc/systemd/system/researcher.service"
        sed -e "s|__USER__|$CURRENT_USER|g" \
            -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
            "$SERVICE_FILE" > "$DEST"
        systemctl daemon-reload
        systemctl enable researcher
        success "Systemd service installed and enabled"
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           Install complete!          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""
echo "  Start service:  make start   (or: sudo systemctl start researcher)"
echo "  View logs:      make logs    (or: journalctl -u researcher -f)"
echo "  Open UI:        http://127.0.0.1:8009/ui"
echo "  Edit config:    nano $PROJECT_DIR/.env"
echo ""
