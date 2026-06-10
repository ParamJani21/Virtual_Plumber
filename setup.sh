#!/bin/bash

set -e

echo "========================================="
echo "  VIRTUAL_PLUMBER Setup Script"
echo "========================================="

# Check if running in WSL or Linux
if grep -qiE "(microsoft|wsl)" /proc/version 2>/dev/null; then
    echo "[INFO] Running in WSL environment"
    IS_WSL=true
else
    echo "[INFO] Running in native Linux environment"
    IS_WSL=false
fi

echo ""
echo "==> Step 1: Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo ""
echo "==> Step 1b: Configuring port..."
read -p "  Use default port 5000? [Y/n]: " port_choice
case "$port_choice" in
    [Nn]*)
        while true; do
            read -p "  Enter custom port number (1024-65535): " custom_port
            if [[ "$custom_port" =~ ^[0-9]+$ ]] && [ "$custom_port" -ge 1024 ] && [ "$custom_port" -le 65535 ]; then
                echo "FLASK_PORT=$custom_port" >> .env
                echo "  [✓] Port set to $custom_port"
                break
            else
                echo "  [!] Invalid port. Enter a number between 1024-65535."
            fi
        done
        ;;
    *)
        echo "  [✓] Using default port 5000"
        ;;
esac

echo "==> Step 2: Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt --break-system-packages

echo "==> Step 3: Installing Security Tools..."

# OpenGrep
echo "  - Installing OpenGrep..."
if command -v opengrep &> /dev/null; then
    echo "    [SKIP] OpenGrep already installed"
else
    curl -fsSL https://raw.githubusercontent.com/opengrep/opengrep/main/install.sh | bash || echo "    [WARN] OpenGrep installation failed"
fi
# OpenGrep installs to ~/.local/bin — ensure it's on PATH for verification
export PATH="$HOME/.local/bin:$PATH"

# Slither
echo "  - Installing Slither..."
if command -v slither &> /dev/null; then
    echo "    [SKIP] Slither already installed"
else
    pip install slither-analyzer --break-system-packages || echo "    [WARN] Slither installation failed"
fi

# Trivy
echo "  - Installing Trivy..."
if command -v trivy &> /dev/null; then
    echo "    [SKIP] Trivy already installed"
else
    # Auto-detect writable install directory
    if [ -w /usr/local/bin ]; then
        INSTALL_DIR="/usr/local/bin"
    else
        INSTALL_DIR="$HOME/.local/bin"
        mkdir -p "$INSTALL_DIR"
    fi
    echo "    [INFO] Installing latest Trivy to $INSTALL_DIR..."
    # Omit version arg to let install.sh fetch the latest release
    if curl -sfL "https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh" | sh -s -- -b "$INSTALL_DIR"; then
        export PATH="$INSTALL_DIR:$PATH"
        echo "    [INFO] Added $INSTALL_DIR to PATH for this session"
    else
        echo "    [WARN] Trivy installation failed"
    fi
fi

# TruffleHog
echo "  - Installing TruffleHog..."
if command -v trufflehog &> /dev/null; then
    echo "    [SKIP] TruffleHog already installed"
else
    if command -v go &> /dev/null; then
        # go install pkg@latest fails when go.mod has replace directives.
        # Workaround: clone the repo and go install from within the module.
        TRUFFLEHOG_TMP=$(mktemp -d)
        echo "    [INFO] Cloning trufflehog repo into $TRUFFLEHOG_TMP..."
        if git clone --depth 1 https://github.com/trufflesecurity/trufflehog.git "$TRUFFLEHOG_TMP" 2>/dev/null; then
            cd "$TRUFFLEHOG_TMP"
            go install ./...
            cd - >/dev/null
            rm -rf "$TRUFFLEHOG_TMP"
        else
            echo "    [WARN] TruffleHog installation failed (git clone error)"
        fi
    else
        echo "    [WARN] Go not found, skipping TruffleHog"
    fi
fi

# ngrok
echo "  - Installing ngrok..."
if command -v ngrok &> /dev/null; then
    echo "    [SKIP] ngrok already installed"
else
    if [ "$IS_WSL" = true ]; then
        echo "    [INFO] Installing ngrok via apt..."
        curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
        echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" | sudo tee /etc/apt/sources.list.d/ngrok.list >/dev/null
        sudo apt update -qq || echo "    [WARN] apt update had errors (non-ngrok repos), continuing..."
        sudo apt install -y ngrok || echo "    [WARN] ngrok installation failed"
    else
        echo "    [INFO] Downloading ngrok binary..."
        if [ -w /usr/local/bin ]; then
            NGROK_DIR="/usr/local/bin"
        else
            NGROK_DIR="$HOME/.local/bin"
            mkdir -p "$NGROK_DIR"
        fi
        wget -q https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz -O /tmp/ngrok.tgz
        tar -xzf /tmp/ngrok.tgz -C "$NGROK_DIR"
        rm -f /tmp/ngrok.tgz
        export PATH="$NGROK_DIR:$PATH"
    fi
fi

# Snyk
echo "  - Installing Snyk..."
if command -v snyk &> /dev/null; then
    echo "    [SKIP] Snyk already installed"
elif command -v npm &> /dev/null; then
    npm install -g snyk || echo "    [WARN] Snyk installation failed"
else
    echo "    [WARN] npm not found, skipping Snyk (install nodejs first)"
fi

echo "==> Step 3b: Cloning semgrep rules..."
if [ -d "rules/semgrep-rules" ] && [ "$(find rules/semgrep-rules -name '*.yaml' 2>/dev/null | wc -l)" -gt 0 ]; then
    echo "  [SKIP] rules/semgrep-rules already exists ($(find rules/semgrep-rules -name '*.yaml' | wc -l) rules)"
else
    echo "  - Cloning semgrep-rules repo..."
    rm -rf rules/semgrep-rules
    mkdir -p rules
    git clone --depth 1 https://github.com/semgrep/semgrep-rules.git rules/semgrep-rules || echo "    [WARN] Rules clone failed"
fi

echo ""
echo "==> Step 4: Verifying installations..."
echo ""

verify_tool() {
    local cmd=$1
    local name=$2
    if command -v "$cmd" &> /dev/null; then
        local version=$($cmd --version 2>&1 | head -1 || echo "installed")
        echo "  ✓ $name: $version"
    else
        echo "  ✗ $name: NOT FOUND"
    fi
}

verify_tool git "Git"
verify_tool opengrep "OpenGrep"
verify_tool slither "Slither"
verify_tool trufflehog "TruffleHog"
verify_tool trivy "Trivy"
verify_tool snyk "Snyk"
verify_tool ngrok "ngrok"

# Verify semgrep rules
if [ -d "rules/semgrep-rules" ]; then
    RULE_COUNT=$(find rules/semgrep-rules -name '*.yaml' 2>/dev/null | wc -l)
    if [ "$RULE_COUNT" -gt 0 ]; then
        echo "  ✓ semgrep-rules: $RULE_COUNT rules"
    else
        echo "  ✗ semgrep-rules: empty directory (will re-clone on next run)"
        rm -rf rules/semgrep-rules
    fi
else
    echo "  ✗ semgrep-rules: NOT FOUND (will clone on next run)"
fi

echo ""
echo "========================================="
echo "  Setup Complete!"
echo "========================================="
echo ""
FLASK_PORT=$(grep -oP '(?<=^FLASK_PORT=)\d+' .env 2>/dev/null || echo "5000")
echo "Next steps:"
echo "  1. Activate virtual environment: source venv/bin/activate"
echo "  2. Run: python3 run.py"
echo "  3. Login at: http://localhost:$FLASK_PORT"
echo "  4. Default admin: admin / Securepass123@#"
echo ""