# VIRTUAL_PLUMBER — Security Scanning Orchestration Dashboard

A Flask-based dashboard that orchestrates security scans across GitHub repositories using OpenGrep, Slither, Trivy, and TruffleHog. Features a 3-tier user system (Admin → Operator → Viewer), PR scanning automation, and a governed false-positive management workflow.

## Features

### Security Scanning
- **GitHub App Integration** — Authenticate and scan repos via GitHub App
- **Selectable Scan Types** — SATS (static analysis), SBOM (CycloneDX), SECRET (secret/token detection)
- **Automated PR Scanning** — Auto-scans PRs on open/synchronize with optional blocking
- **GitHub Status Checks** — Real-time commit status on every PR
- **PR Comments** — Posts scan summary as markdown table on the PR

### User System (3-Tier)
| Role | Permissions |
|------|------------|
| **Admin** | Full access — manage all users, configure settings, approve FP at final stage |
| **Operator** | Manage their own viewers, review and escalate viewer-submitted FPs, trigger scans |
| **Viewer** | Submit false positive requests, view scan results, export reports |

Each Operator can create Viewers. A Viewer's FP requests are routed to their parent Operator only — other Operators cannot see them.

### False Positive Management (3-Tier Approval)
```
Viewer submits → PENDING_OPERATOR → Operator approves → PENDING_ADMIN → Admin approves → APPROVED_FP
                                                      ↘ Operator rejects → OPERATOR_REJECTED
                                                                                              ↘ Admin rejects → ADMIN_REJECTED
                                                                                              ↘ Admin reverts → REVERTED_TO_TP
```
- Viewers submit FP requests with a reason
- Operators review, approve (escalates to admin), or reject
- Administrators give final approval or reject/revert
- Approved FPs are suppressed in scan results

### Activity Logging
- Every action (login, user CRUD, scan trigger, FP submission/approval/rejection) is logged
- Admin can view activity logs per user with date/action/resource filters

### Export Reports
- Generate HTML reports filtered by date range, severity, and tool

## Prerequisites

- Python 3.10+
- GitHub App (create at github.com/settings/apps)
- ngrok account (for webhook tunnel)
- WSL (Windows Subsystem for Linux) — required on Windows for Git/Security tools

## Quick Start

### 1. Setup

```bash
cd VIRTUAL_PLUMBER
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Install security tools in WSL/Linux:
```bash
# OpenGrep
curl -fsSL https://raw.githubusercontent.com/opengrep/opengrep/main/install.sh | bash

# Slither (optional, for smart contracts)
pip install slither-analyzer

# Trivy (SBOM)
curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sudo sh -s -- -b /usr/local/bin v0.70.0

# TruffleHog (secrets)
go install github.com/trufflesecurity/trufflehog/v3@latest

# ngrok
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update && sudo apt install ngrok
```

### 2. Configure GitHub App

1. Go to https://github.com/settings/apps/new
2. Set name (e.g., `VIRTUAL_PLUMBER`)
3. Set any Homepage URL and Webhook URL (update later with ngrok URL)
4. Permissions:
   - Contents: Read
   - Pull requests: Read & Write
   - Commit statuses: Read & Write
   - Checks: Read & Write
5. Subscribe to: Pull requests
6. Generate and download a private key (.pem)

### 3. Run

```bash
python3 run.py
```

First launch creates a default admin: `admin / Securepass123@#` (force-changed on first login).

### 4. Dashboard Setup

1. **Login** as admin
2. **Settings tab** — Enter GitHub App ID, App Name, Private Key, ngrok token, webhook secret
3. **Restart `run.py`** to pick up `.env` changes
4. **Set webhook URL** in GitHub App settings (shown in terminal after ngrok starts)
5. **Install** the GitHub App on your repos

## User Management

### Creating Users (Settings → Users tab)

| Creator | Can create |
|---------|-----------|
| Admin | Admin, Operator, Viewer |
| Operator | Viewer only |

Each user created by an Operator is automatically linked as their child. That Operator will see only their own Viewers and all Admins in the user list.

### Password Policy
- Minimum 12 characters
- Must contain uppercase, lowercase, digit, and special character
- Cannot contain username
- Password history (last 5) enforced on change
- First login forces password change
- 5 failed attempts = 15-minute lockout

## API Endpoints

### Authentication
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/login` | GET/POST | Login page and processing |
| `/auth/logout` | GET/POST | Logout |
| `/auth/change-password` | GET/POST | Change password (forced on first login) |
| `/auth/status` | GET | Current auth status |
| `/auth/setup/initial-admin` | POST | Create initial admin (only if no admin exists) |

### Dashboard & Scans
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard |
| `/api/me` | GET | Current user info |
| `/api/overview` | GET | Dashboard stats |
| `/api/history` | GET | Scan history |
| `/api/history/<scan_id>` | GET | Scan detail |
| `/api/repos` | GET | List repos |
| `/api/repos/scan` | POST | Trigger scan on one repo |
| `/api/repos/scan-all` | POST | Trigger scan on all repos |
| `/api/settings` | GET/POST | App settings |

### User Management
| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/users` | GET | Admin/Operator | List users (Operator sees only admins + their viewers) |
| `/api/users` | POST | Admin/Operator | Create user (Operator can only create Viewer) |
| `/api/users/<id>` | PUT | Admin/Operator | Update user (Operator can only edit their own viewers) |
| `/api/users/<id>` | DELETE | Admin/Operator | Delete user (Operator can only delete their own viewers) |

### False Positive Management
| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/fp/requests` | GET | All | List FP requests (scoped by role) |
| `/api/fp/requests` | POST | All | Submit FP request |
| `/api/fp/requests/<id>` | GET | All | FP request detail |
| `/api/fp/requests/<id>/approve` | POST | Operator/Admin | Approve FP |
| `/api/fp/requests/<id>/reject` | POST | Operator/Admin | Reject FP |
| `/api/fp/requests/<id>/revert` | POST | Admin | Revert approved FP to TP |
| `/api/fp/pending-count` | GET | Operator/Admin | Pending review count (scoped to operator's viewers) |
| `/api/fp/queue` | GET | Operator/Admin | Review queue (scoped to operator's viewers) |
| `/api/fp/check/<fingerprint>` | GET | All | Check if fingerprint is suppressed |
| `/api/fp/batch-check` | POST | All | Batch check fingerprints |

### Activity & Reporting
| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/activity` | GET | Admin | Activity logs with filters |
| `/api/activity/users` | GET | Admin | User activity stats |
| `/api/export-report` | GET | All | Export HTML report |

### Webhook
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/github/webhook` | POST | GitHub webhook receiver |

## Project Structure

```
VIRTUAL_PLUMBER/
├── run.py                    # Entry point (auto-update on startup)
├── requirements.txt          # Python dependencies
├── .env                      # Config (auto-generated from Settings)
├── setup.sh                  # Automated setup script
├── AGENTS.md                 # Agent/developer documentation
├── app/
│   ├── __init__.py           # App factory, DB init, blueprints
│   ├── routes.py             # Dashboard + core API endpoints
│   ├── auth_routes.py        # Login/logout/password management
│   ├── fp_routes.py          # False positive API endpoints
│   └── templates/            # HTML templates
│       ├── dashboard.html
│       ├── login.html
│       ├── change_password.html
│       ├── fp_dashboard.html
│       ├── scan_detail.html
│       └── user_activity.html
├── static/
│   ├── dashboard.js          # Main frontend logic
│   ├── fp.js                 # FP management frontend
│   ├── styles.css
│   ├── styles-base.css
│   ├── styles-components.css
│   └── styles-responsive.css
├── auth/
│   ├── __init__.py
│   ├── decorators.py         # @require_login, @require_admin, @require_role
│   └── utils.py              # Session management, audit logging
├── modules/
│   ├── control_apis.py       # Core scan workflow (clone, scan, merge)
│   ├── repos.py              # GitHub App JWT auth, repo fetching
│   ├── history.py            # Scan history data
│   ├── fp_manager.py         # FP request lifecycle (submit → approve → reject → revert)
│   ├── pr_scan_handler.py    # PR scan orchestration
│   ├── github_status.py      # GitHub commit status checks
│   ├── pr_comment.py         # PR comment posting
│   ├── settings.py           # Settings management
│   ├── scan_api.py           # Scan API endpoints
│   ├── scan_controller.py    # Scan orchestration
│   └── env_config.py         # Environment configuration
├── models/
│   ├── database.py           # User, Session, AuditLog, ScanHistory models
│   └── false_positive.py     # FalsePositiveRecord model
├── utils/
│   ├── crypto_utils.py       # Encryption utilities
│   └── fingerprint.py        # Finding fingerprint generation
├── validators/
│   └── input_validators.py   # Username/password/email validation
├── logs/
│   ├── app.log
│   └── tool-output/{scan_id}/
│       ├── merged.json
│       ├── opengrep.json
│       ├── truffle.json
│       └── trivy.json
└── tmp/                      # Cloned repos (auto-cleaned)
```

## Troubleshooting

```bash
# Check logs
tail -f logs/app.log

# Verify tools
which opengrep trufflehog trivy git

# Quick DB check
sqlite3 virtual_plumber.db "SELECT * FROM scan_history ORDER BY created_at DESC LIMIT 5;"

# Test scan API
curl http://localhost:5000/api/history
curl http://localhost:5000/api/overview
```

### Common Issues
1. **WSL paths** — Always use `get_wsl_path()` for Windows → WSL path conversion
2. **Token expiration** — GitHub JWT expires after 5 minutes (handled by repos.py)
3. **RSA key format** — `.env` uses escaped `\n`, restored by env_config.py
4. **Trivy SBOM only** — Uses `trivy sbom --format cyclonedx`, not vulnerability scans
5. **Missing tools** — Scan continues but marks tool as `skipped`
6. **Webhook signature** — Must match between GitHub App settings and dashboard
