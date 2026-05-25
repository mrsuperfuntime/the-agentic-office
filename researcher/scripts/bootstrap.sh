#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════╗
# ║  THE RESEARCHER — Full System Bootstrap                         ║
# ║  Run once on a fresh Ubuntu 24.04 install                       ║
# ║                                                                  ║
# ║  Usage (after OS install, logged in as your user):              ║
# ║    bash <(curl -fsSL https://raw.githubusercontent.com/         ║
# ║      mrsuperfuntime/the-agentic-office/main/                    ║
# ║      researcher/scripts/bootstrap.sh)                           ║
# ║                                                                  ║
# ║  Or if you already cloned the repo:                             ║
# ║    bash scripts/bootstrap.sh                                     ║
# ║                                                                  ║
# ║  Unattended (no prompts — used by first-boot systemd service):  ║
# ║    UNATTENDED=true bash scripts/bootstrap.sh                    ║
# ╚══════════════════════════════════════════════════════════════════╝
set -euo pipefail

# Set before first use — callers can override via env var
UNATTENDED="${UNATTENDED:-false}"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[✓]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[!]${NC}    $*"; }
step()    { echo -e "\n${BOLD}${CYAN}──────────────────────────────────────${NC}"; echo -e "${BOLD} $*${NC}"; echo -e "${BOLD}${CYAN}──────────────────────────────────────${NC}"; }
die()     { echo -e "${RED}[✗] $*${NC}" >&2; exit 1; }

CURRENT_USER="$(whoami)"
HOME_DIR="$HOME"
REPO_URL="https://github.com/mrsuperfuntime/the-agentic-office.git"
INSTALL_DIR="$HOME_DIR/researcher"

echo ""
echo -e "${CYAN}${BOLD}"
cat << 'EOF'
  ████████╗██╗  ██╗███████╗    ██████╗ ███████╗███████╗███████╗ █████╗ ██████╗  ██████╗██╗  ██╗███████╗██████╗
  ╚══██╔══╝██║  ██║██╔════╝    ██╔══██╗██╔════╝██╔════╝██╔════╝██╔══██╗██╔══██╗██╔════╝██║  ██║██╔════╝██╔══██╗
     ██║   ███████║█████╗      ██████╔╝█████╗  ███████╗█████╗  ███████║██████╔╝██║     ███████║█████╗  ██████╔╝
     ██║   ██╔══██║██╔══╝      ██╔══██╗██╔══╝  ╚════██║██╔══╝  ██╔══██║██╔══██╗██║     ██╔══██║██╔══╝  ██╔══██╗
     ██║   ██║  ██║███████╗    ██║  ██║███████╗███████║███████╗██║  ██║██║  ██║╚██████╗██║  ██║███████╗██║  ██║
     ╚═╝   ╚═╝  ╚═╝╚══════╝    ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
EOF
echo -e "${NC}"
echo -e "  ${BOLD}Alienware m15 — Linux Bootstrap${NC}  |  User: ${CYAN}$CURRENT_USER${NC}"
if [[ "$UNATTENDED" == "true" ]]; then
    echo -e "  ${YELLOW}UNATTENDED mode — all prompts answered automatically${NC}"
fi
echo ""

# ── Sanity checks ─────────────────────────────────────────────────────────────
[[ "$(uname -s)" == "Linux" ]]        || die "Linux only."
[[ "$EUID" -ne 0 ]]                   || die "Do NOT run as root. Run as your normal user — sudo will be called when needed."
command -v apt-get &>/dev/null        || die "Ubuntu/Debian required (apt not found)."
grep -qi "ubuntu" /etc/os-release     || warn "Not Ubuntu — continuing anyway, but untested."

# ── Step 1: System update ─────────────────────────────────────────────────────
step "1 / 9  System update"
sudo apt-get update -qq
sudo apt-get upgrade -y -qq
sudo apt-get install -y -qq \
    curl wget git build-essential software-properties-common \
    apt-transport-https ca-certificates gnupg lsb-release \
    openssh-server ufw htop net-tools
success "Base packages installed"

# ── Step 2: Python 3.11 ───────────────────────────────────────────────────────
step "2 / 9  Python 3.11"
if ! command -v python3.11 &>/dev/null; then
    sudo add-apt-repository -y ppa:deadsnakes/ppa
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3.11 python3.11-venv python3.11-dev
fi
success "$(python3.11 --version)"

# ── Step 3: NVIDIA drivers ────────────────────────────────────────────────────
step "3 / 9  NVIDIA drivers (Alienware GPU)"
NEEDS_REBOOT=false
if command -v nvidia-smi &>/dev/null; then
    success "NVIDIA drivers already installed: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)"
else
    info "Detecting best NVIDIA driver..."
    sudo apt-get install -y -qq ubuntu-drivers-common
    RECOMMENDED="$(ubuntu-drivers devices 2>/dev/null | grep recommended | awk '{print $3}' | head -1)"
    if [[ -n "$RECOMMENDED" ]]; then
        info "Installing recommended driver: $RECOMMENDED"
        sudo apt-get install -y -qq "$RECOMMENDED"
        warn "NVIDIA driver installed. A reboot is needed before GPU acceleration works."
        warn "After rebooting, re-run this script — it will skip already-completed steps."
        NEEDS_REBOOT=true
    else
        warn "No NVIDIA driver auto-detected. Install manually: sudo ubuntu-drivers autoinstall"
    fi
fi

# ── Step 4: OpenSSH server + firewall ─────────────────────────────────────────
step "4 / 9  SSH server + firewall"
sudo systemctl enable ssh --now
sudo ufw allow OpenSSH
sudo ufw allow 8009/tcp comment "THE RESEARCHER UI (LAN only)"
sudo ufw --force enable
success "SSH running on port 22"
success "Firewall active — SSH + port 8009 open"

# Get local IP for the connection instructions
LOCAL_IP="$(hostname -I | awk '{print $1}')"
success "Local IP: $LOCAL_IP"

# ── Step 5: SSH key setup for VS Code Remote ──────────────────────────────────
step "5 / 9  SSH key (VS Code Remote access)"
SSH_DIR="$HOME_DIR/.ssh"
AUTH_KEYS="$SSH_DIR/authorized_keys"
mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"
touch "$AUTH_KEYS"
chmod 600 "$AUTH_KEYS"

# Harden SSH config
sudo tee /etc/ssh/sshd_config.d/99-researcher.conf > /dev/null << SSHEOF
PasswordAuthentication yes
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
X11Forwarding no
SSHEOF
sudo systemctl reload ssh
success "SSH configured for VS Code Remote"

# ── Step 6: Tailscale (optional — remote access from anywhere) ────────────────
step "6 / 9  Tailscale (remote access outside LAN)"
TAILSCALE_INSTALLED=false
TAILSCALE_IP="not-installed"

if [[ "$UNATTENDED" == "true" ]]; then
    info "UNATTENDED: skipping Tailscale (requires interactive browser login)."
    info "To install later:  curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up"
else
    echo ""
    echo "  Tailscale is a zero-config VPN. It lets you connect to this machine"
    echo "  from VS Code on your Windows PC even when you're not on the same network."
    echo "  Free for personal use, no port forwarding needed."
    echo ""
    read -rp "  Install Tailscale? [Y/n]: " install_tailscale
    if [[ "${install_tailscale:-Y}" =~ ^[Yy]$ ]]; then
        curl -fsSL https://tailscale.com/install.sh | sh
        sudo tailscale up
        TAILSCALE_IP="$(tailscale ip -4 2>/dev/null || echo 'run: tailscale ip -4')"
        success "Tailscale installed. Your Tailscale IP: $TAILSCALE_IP"
        TAILSCALE_INSTALLED=true
    else
        info "Skipping Tailscale — you can install it later with: curl -fsSL https://tailscale.com/install.sh | sh"
    fi
fi

# ── Step 7: Ollama + GPU ──────────────────────────────────────────────────────
step "7 / 9  Ollama + GPU"
if command -v ollama &>/dev/null; then
    success "Ollama already installed: $(ollama --version 2>/dev/null || echo 'version unknown')"
else
    info "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    success "Ollama installed"
fi

# Check GPU is visible to Ollama
if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
    GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
    success "GPU available to Ollama: $GPU_NAME"
else
    warn "GPU not yet visible — reboot required after NVIDIA driver install"
fi

# Pull recommended model
sudo systemctl enable ollama --now 2>/dev/null || true
sleep 2
if ollama list 2>/dev/null | grep -q "qwen2.5:7b"; then
    success "qwen2.5:7b already pulled"
else
    info "Pulling qwen2.5:7b (~4.7 GB — best tool-calling model for your GPU)..."
    ollama pull qwen2.5:7b
    success "qwen2.5:7b ready"
fi

# ── Step 8: Clone and install the researcher ──────────────────────────────────
step "8 / 9  THE RESEARCHER project"
if [[ -d "$INSTALL_DIR" ]]; then
    info "Project already exists at $INSTALL_DIR — pulling latest..."
    git -C "$INSTALL_DIR" pull
else
    info "Cloning from $REPO_URL ..."
    git clone "$REPO_URL" /tmp/agentic-office-clone
    cp -r /tmp/agentic-office-clone/researcher "$INSTALL_DIR"
    rm -rf /tmp/agentic-office-clone
fi

# Set up venv + deps
info "Setting up Python environment..."
python3.11 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
success "Python environment ready"

# Bootstrap .env
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    sed -i 's/^RESEARCHER_MODEL=.*/RESEARCHER_MODEL=qwen2.5:7b/' "$INSTALL_DIR/.env"
    warn ".env created — add your Thingiverse and eBay credentials: nano $INSTALL_DIR/.env"
fi

# Install systemd service
info "Installing systemd service..."
sudo bash -c "
    sed -e 's|__USER__|$CURRENT_USER|g' \
        -e 's|__PROJECT_DIR__|$INSTALL_DIR|g' \
        '$INSTALL_DIR/researcher.service' \
        > /etc/systemd/system/researcher.service
    systemctl daemon-reload
    systemctl enable researcher
"
sudo systemctl start researcher
success "researcher service installed, enabled, and started"

# ── Remove temporary NOPASSWD sudoers (added by autoinstall late-commands) ────
BOOTSTRAP_SUDOERS="/etc/sudoers.d/researcher-bootstrap"
if [[ -f "$BOOTSTRAP_SUDOERS" ]]; then
    sudo rm -f "$BOOTSTRAP_SUDOERS"
    info "Removed temporary NOPASSWD sudoers entry"
fi

# ── Step 9: VS Code Remote connection info ────────────────────────────────────
step "9 / 9  VS Code Remote SSH setup (Windows side)"

cat << VSCODE_INSTRUCTIONS

  Add this to your Windows SSH config:
  File: C:\\Users\\<your-windows-user>\\.ssh\\config

  ┌─────────────────────────────────────────────────────────────┐
  │                                                             │
  │  Host $(hostname)-lan                                       │
  │      HostName $LOCAL_IP
  │      User $CURRENT_USER
  │      Port 22                                                │
  │                                                             │
VSCODE_INSTRUCTIONS

if [[ "$TAILSCALE_INSTALLED" == "true" ]]; then
cat << VSCODE_TAILSCALE
  │  Host $(hostname)                                           │
  │      HostName $TAILSCALE_IP
  │      User $CURRENT_USER
  │      Port 22                                                │
  │                                                             │
VSCODE_TAILSCALE
fi

cat << VSCODE_INSTRUCTIONS2
  └─────────────────────────────────────────────────────────────┘

  Then in VS Code (Windows):
    1. Install extension: Remote - SSH  (ms-vscode-remote.remote-ssh)
    2. Press Ctrl+Shift+P → "Remote-SSH: Connect to Host"
    3. Pick "$(hostname)-lan" (or "$(hostname)" for Tailscale)
    4. Open folder: $INSTALL_DIR
    5. Install the Python extension on the remote

  Push code from Windows to Linux:
    - VS Code Remote SSH edits files directly on this machine
    - Or: git push from Windows → git pull on this machine

VSCODE_INSTRUCTIONS2

# ── Passwordless SSH key instructions ────────────────────────────────────────
if [[ "$UNATTENDED" != "true" ]]; then
    echo "  To enable passwordless login from Windows, paste your Windows public key"
    echo "  into: $AUTH_KEYS"
    echo ""
    echo "  Get your Windows public key by running in PowerShell:"
    echo "    Get-Content \$env:USERPROFILE\\.ssh\\id_rsa.pub"
    echo "  Then on this machine:"
    echo "    echo '<paste key here>' >> ~/.ssh/authorized_keys"
    echo ""
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo -e "${GREEN}${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║            Bootstrap complete!                       ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "  Researcher UI:   http://$LOCAL_IP:8009/ui"
echo "  Researcher logs: journalctl -u researcher -f"
echo "  Ollama models:   ollama list"
echo "  Project dir:     $INSTALL_DIR"
echo ""

if [[ "$NEEDS_REBOOT" == "true" ]]; then
    echo -e "${YELLOW}  ⚠  REBOOT REQUIRED for NVIDIA drivers to activate.${NC}"
    echo -e "${YELLOW}  After reboot, GPU will be available and Ollama will use it.${NC}"
    echo ""
    if [[ "$UNATTENDED" == "true" ]]; then
        warn "UNATTENDED: rebooting automatically in 30 seconds..."
        warn "To cancel:  sudo shutdown -c"
        sleep 30
        sudo reboot
    else
        read -rp "  Reboot now? [Y/n]: " do_reboot
        if [[ "${do_reboot:-Y}" =~ ^[Yy]$ ]]; then
            sudo reboot
        fi
    fi
fi
