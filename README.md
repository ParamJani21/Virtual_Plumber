# VIRTUAL_PLUMBER - Security Scanning Orchestration Dashboard

A Flask-based security scanning dashboard that automates security scans for GitHub repositories using multiple security tools.

## Features

- **GitHub App Integration** - Authenticate and scan repositories via GitHub App
- **Automated PR Scanning** - Automatically scans pull requests when opened/updated
- **PR Toggle** - Enable/disable automatic PR scanning from Settings
- **GitHub Status Checks** - Real-time commit status on PRs
- **PR Comments** - Posts scan results summary as PR comment
- **Selectable Scan Types** - Choose which scans to run (SATS, SBOM, SECRET)
- **Scan History** - View and manage past scan results
- **Export Reports** - Generate HTML reports of scan findings

## Prerequisites

- Python 3.10+
- GitHub App (create at github.com/settings/apps)
- ngrok (for webhook access)
- WSL (Windows Subsystem for Linux) for Windows users

## Installation

### 1. Clone/Download the Project

```bash
cd /VIRTUAL_PLUMBER
```

### 2. Quick Setup (Recommended)

Run the automated setup script - it creates virtual environment, installs dependencies, and all security tools:

```bash
chmod +x setup.sh
./setup.sh
```

### 3. Manual Installation (Alternative)

If you prefer manual installation:

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt --break-system-packages
```

#### Install Security Tools (WSL/Linux)

```bash
# OpenGrep (static analysis)
curl -fsSL https://raw.githubusercontent.com/opengrep/opengrep/main/install.sh | bash

# Slither (smart contract analysis - optional)
pip install slither-analyzer

# Trivy (SBOM generation)
curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sudo sh -s -- -b /usr/local/bin v0.70.0

# TruffleHog (secret scanning)
git clone https://github.com/trufflesecurity/trufflehog.git
cd trufflehog && go install

# ngrok

curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null && echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" | sudo tee /etc/apt/sources.list.d/ngrok.list && sudo apt update && sudo apt install ngrok
```

Verify tools:
```bash
git --version
opengrep --version
slither --version
trufflehog --version
trivy --version
ngrok --version
```

## Setup Flow

### 1. Run the run.py

```bash
python3 run.py
```

* It will guide you how to do all the things, if any doubts here is the more detailed guide present.

### GITHUB APPLICATION SETUP
1. Go to: https://github.com/settings/apps/new
2. Set name (e.g., "VIRTUAL_PLUMBER")
3. Enter the random URL at the HomepageURL and webhookURL(TEMP, we need to change it when we get the NGROK URL or If you are planning to match it with the domain via HTTPS, then just enter the https://DOMAIN/github/webhook)
4. Permissions:
   - Contents: Read
   - Pull requests: Read & Write
   - Commit statuses: Read & Write
   - Checks: Read & Write
5. Subscribe to events: `Pull requests`
6. Create Gihub app.
7. Find private key generation...and generate private key (download .pem file)

Access at: `http://localhost:5000`

### 2. Configure via Dashboard

1. **Login** with admin : Securepass123@# --> Don't worry we force to change this password...!


2. **Configure GitHub App Settings** (in Settings Tab):
   - **GitHub App ID** - From your GitHub App settings
   - **GitHub App Name** - The name you gave your app
   - **GitHub Secret Key** - Paste the entire private key (.pem file contents)
   - **Ngrok OAuth Token** - From ngrok.com dashboard
   - **Ngrok Subdomain** - From ngrok.com dashboard --> go to the domain and create one for the static. (if it is like `https://your-subdomain.ngrok.io` then just enter the `your-subdomain` in the setting field of Ngrok subdomain.)
   - **Webhook Secret** - Generate a random string for verification

### RESTART THE PYTHON RUN.PY AGAIN if you have setup it from the dashboard TO PICK UP THE .ENV FILE CONFIGURATIONS (**MANDETORY**)

3. **Configure GitHub Webhook**:
   - Go to your GitHub App settings > Webhooks
   - Add webhook URL (shown in terminal when app starts): `https://your-subdomain.ngrok.io/github/webhook`
   - Set webhook secret matching your dashboard

4. **Install GitHub App** on your organization/repositories

**Note:** Ngrok tunnel is automatically started when `Ngrok OAuth Token` is configured. The webhook URL will be displayed in the terminal.

### 4. Toggle PR Scanning

In Settings tab:
- Enable toggle = All PRs auto-scan
- Disable toggle = PRs logged but not scanned


**Important: Change password after first login!**

## Scan Types

| Type | Tool | Description |
|------|------|-------------|
| **SATS** | OpenGrep | Static code analysis |
| **SBOM** | Trivy | Software Bill of Materials |
| **SECRET** | TruffleHog | Secret/token detection |



## Troubleshooting

### Check logs
```bash
tail -f logs/app.log
```

### Verify tools installed
```bash
which opengrep trufflehog trivy git
```

## Project Structure

```
VIRTUAL_PLUMBER/
├── run.py                 # App entry point
├── requirements.txt      # Dependencies
├── .env                  # Auto-created config
├── app/                  # Flask app
│   ├── __init__.py
│   ├── routes.py
│   └── templates/
├── modules/              # Core logic
│   ├── control_apis.py
│   ├── pr_scan_handler.py
│   ├── github_status.py
│   └── pr_comment.py
├── models/               # Database
│   └── database.py
├── static/               # Frontend
│   ├── dashboard.js
│   └── styles.css
└── logs/                 # Output
    ├── app.log
    └── tool-output/
```

## Need Help?

1. Check `logs/app.log` for errors
2. Verify all tools are in PATH
3. Ensure ngrok tunnel is active
4. Verify GitHub App permissions and webhook
