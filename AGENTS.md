# VIRTUAL_PLUMBER - Agent Documentation

## Project Overview

**VIRTUAL_PLUMBER** is a Flask-based security scanning orchestration dashboard for GitHub repositories. It automates security scans by integrating multiple security tools (OpenGrep, Slither, Trivy, TruffleHog) and provides a web dashboard for managing scans and viewing results. 

## WE ARE USING THE OPENGREP, SO DON"T EVER MENTION THE SEMGREP...!

### Key Capabilities
- **GitHub App Integration** - Authenticate and scan repositories via GitHub App
- **SATS (Static Analysis)** - OpenGrep + Slither for security vulnerability detection
- **SBOM (Software Bill of Materials)** - Trivy for generating SBOM (CycloneDX format)
- **Secret Scanning** - TruffleHog for detecting exposed secrets, tokens, and credentials
- **Selectable Scan Types** - Choose which scans to run (SATS, SBOM, SECRET, or any combination)
- **Automated PR Scanning** - Automatically scans pull requests when opened/updated
- **GitHub Status Checks** - Real-time commit status on PRs
- **PR Comments** - Posts scan results summary as PR comment
- **Scan History** - View and manage past scan results
- **Export Reports** - Generate HTML reports of scan findings

**Not a library.** Flask web app with Python business logic. No tests, CI, or build process.

---

## Quick Start

```bash
cd /mnt/e/onlydash_VIRTUAL_PLUMBER/VIRTUAL_PLUMBER
python3 run.py
# Dashboard at http://localhost:5000
# ngrok tunnel auto-created if NGROK_OAUTH_TOKEN configured
```

### API - Single Scan
```bash
curl -X POST http://localhost:5000/api/repos/scan \
  -H "Content-Type: application/json" \
  -d '{"repo_id":"123","repo_name":"my-repo","repo_owner":"my-org","repo_url":"...","repo_branch":"main","scan_types":["sats","sbom","secret"]}'
```

### API - Scan All Repos
```bash
curl -X POST http://localhost:5000/api/repos/scan-all \
  -H "Content-Type: application/json" \
  -d '{"scan_types":["sats","sbom","secret"]}'
```

---

## File Structure

```
VIRTUAL_PLUMBER/
├── run.py                      # Flask app entry point
├── requirements.txt             # Python dependencies
├── .env                        # Configuration (tokens, secrets)
├── app/
│   ├── __init__.py             # App factory, DB init, auth config
│   ├── routes.py               # Dashboard + API endpoints
│   ├── templates/              # HTML templates
│   └── static/
│       ├── dashboard.js        # Frontend JavaScript
│       └── styles.css          # Styles
├── modules/
│   ├── control_apis.py         # Core scan workflow
│   ├── repos.py                # GitHub App JWT auth, repo fetching
│   ├── history.py              # Scan history data
│   ├── pr_scan_handler.py      # PR scan orchestration
│   ├── github_status.py        # GitHub status checks
│   ├── pr_comment.py           # PR comment posting
│   ├── settings.py             # Settings management
│   └── env_config.py           # Environment config
├── models/
│   └── database.py             # SQLAlchemy models
├── logs/
│   ├── app.log                 # Application logs
│   └── tool-output/{scan_id}/  # Scan results
│       ├── merged.json         # Combined findings
│       ├── opengrep.json       # Static analysis results
│       ├── truffle.json        # Secret scan results
│       └── trivy.json          # SBOM results
└── tmp/                        # Cloned repos (auto-cleaned)
```

---

## Scan Types

| Type | Tool | Description | Failure Behavior |
|------|------|-------------|-------------------|
| `sats` | OpenGrep + Slither | Static code analysis | **Blocks workflow** |
| `sbom` | Trivy | Software Bill of Materials (CycloneDX) | Non-blocking |
| `secret` | TruffleHog | Secret scanning | Non-blocking |

Frontend shows modal with checkboxes to select which scans to run.

---

## Core Workflow (6 Steps)

```
1. CLONE    → Git clone via GitHub App token to /tmp/{owner}/{name}/
2. SCANS    → Run selected tools based on scan_types parameter
3. MERGE    → Combine findings in merge_findings()
4. SAVE     → Store to logs/tool-output/{scan_id}/
5. CLEANUP  → Remove cloned repo from /tmp/
```

---

## PR Scanning (Automated)

When PRs are opened or updated in GitHub, VIRTUAL_PLUMBER automatically:

1. Receives webhook event at `/github/webhook`
2. Triggers background security scan (SATS/SBOM/SECRET)
3. Sets GitHub status: `pending` → `success/failure`
4. Posts findings summary as PR comment
5. Displays results in dashboard History tab

### PR Webhook Events
- **opened** - Triggers new scan
- **reopened** - Triggers new scan
- **synchronize** - Triggers re-scan with new commits
- **closed** - Logs PR close (no scan)

### GitHub Status Check States
```
⏳ pending      → "Scanning for security vulnerabilities..."
✅ success      → "Found 0 issues" (or "Found N issues")
⚠️ neutral      → "Found N high/medium issues"
❌ failure      → "N critical issues"
```

### PR Comment Format
Posts markdown table to PR:
```
## 🔍 VIRTUAL_PLUMBER Security Scan Results

| Severity | File | Line | Finding |
|:---------|:-----|:-----|:--------|
| CRITICAL | `csai_key.pem` | 1 | Detected Private Key |
| MEDIUM | `test.py` | 13 | Formatted Sql Query |
...
```

---

## GitHub App Authentication

### Configuration (.env)
```env
GITHUB_APP_ID=3056984
GITHUB_APP_NAME=proeperthingthisis
GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
GITHUB_WEBHOOK_SECRET=your_webhook_secret
NGROK_OAUTH_TOKEN=your_ngrok_token
```

### Key Points
- `GITHUB_APP_ID` - GitHub App ID (e.g., 3056984)
- `GITHUB_PRIVATE_KEY` - RSA private key (escaped `\n` in .env)
- `GITHUB_WEBHOOK_SECRET` - HMAC secret for webhook signature verification
- JWT expires after 5 minutes, repos.py handles token refresh

### Permissions Required
- `checks:write` - Create/update check runs
- `contents:write` - Clone repositories
- `pull_requests:write` - Post comments
- `statuses:write` - Set commit status

---

## WSL Execution

All external tools (Git, Trivy, OpenGrep, TruffleHog) run via WSL on Windows:

```python
def run_wsl_command(command, cwd=None, timeout=300):
    # Windows paths converted: C:\foo → /mnt/c/foo
    # Use get_wsl_path() for Windows-to-WSL conversion
```

### Install Tools in WSL
```bash
# OpenGrep
go install github.com/PatrickKhanz/owasp-gpt@latest

# Slither
pip install slither-analyzer

# Trivy
wsl wget https://github.com/aquasecurity/trivy/releases/download/v0.51.0/trivy_0.51.0_Linux-64bit.tar.gz -O /tmp/trivy.tar.gz
wsl tar zxvf /tmp/trivy.tar.gz -C /usr/local/bin/

# TruffleHog
go install github.com/trufflesecurity/trufflehog/v3@latest

# Verify
wsl git --version
wsl opengrep --version
wsl trufflehog --version
```

---

## Key Modules

### modules/control_apis.py
- `trigger_scan()` - Main entry point, 6-step workflow
- `clone_repository()` - Git clone with GitHub App auth
- `run_opengrep_scan()` - Static analysis
- `run_truffle_scan()` - Secret scanning
- `run_trivy_scan()` - SBOM generation
- `merge_findings()` - Combine results, remove duplicates
- `save_scan_results()` - Write JSON files

### modules/pr_scan_handler.py
- `trigger_pr_scan()` - Create ScanHistory, start background thread
- `_run_pr_scan_background()` - Execute scan, update status, post comment

### modules/github_status.py
- `set_github_status_check()` - Set commit status on PR

### modules/pr_comment.py
- `post_pr_comment()` - Post markdown comment to PR
- `generate_scan_summary_comment()` - Format findings table

### modules/repos.py
- `get_installations()` - Get GitHub App installations
- `get_installation_token()` - Get OAuth token for API calls
- `get_repo_installation_id()` - Get installation ID for repo

---

## Data Structures

### merged.json
```json
{
  "scan_id": "pr-42-20240115-143022",
  "timestamp": "2024-01-15T14:30:22Z",
  "repo_name": "my-repo",
  "repo_owner": "my-org",
  "repo_branch": "main",
  "scan_source": "pr_webhook",
  "is_pr_scan": true,
  "pr_number": 42,
  "pr_title": "Add authentication feature",
  "pr_head_ref": "refs/pull/42/head",
  "scan_types": ["sats", "sbom", "secret"],
  "summary": {
    "total_unique": 5,
    "by_severity": {"CRITICAL": 1, "MEDIUM": 2, "LOW": 2},
    "by_category": {"secrets": 2, "code": 3},
    "tool_breakdown": {"opengrep": 3, "trufflehog": 2, "trivy": 0}
  },
  "findings": [...]
}
```

### Finding Format
```json
{
  "id": "1",
  "file": "csai_key.pem",
  "line": 1,
  "type": "private_key",
  "title": "Detected Private Key",
  "message": "Private Key detected...",
  "severity": "CRITICAL",
  "category": "secrets",
  "cwe": ["CWE-798"],
  "sources": ["opengrep", "trufflehog"]
}
```

---

## Debugging

### View Logs
```bash
tail -f logs/app.log
```

### Check Scan Results
```bash
ls logs/tool-output/{scan_id}/
cat logs/tool-output/{scan_id}/merged.json
```

### Test API
```bash
curl http://localhost:5000/api/history
curl http://localhost:5000/api/overview
```

### Check Database
```bash
sqlite3 virtual_plumber.db "SELECT * FROM scan_history ORDER BY created_at DESC LIMIT 5;"
```

### Test Webhook Manually
```bash
SECRET="your_webhook_secret"
PAYLOAD='{"zen":"Design for failure."}'
SIGNATURE="sha256=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" -hex | cut -d' ' -f2)"

curl -X POST http://localhost:5000/github/webhook \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: $SIGNATURE" \
  -H "X-GitHub-Event: ping" \
  -d "$PAYLOAD"
```

---

## Common Pitfalls

1. **WSL paths** - Always use `get_wsl_path()` for Windows-to-WSL conversion
2. **Token expiration** - JWT expires after 5 minutes, handled by repos.py
3. **RSA key format** - `.env` uses escaped `\n`, restored by env_config.py
4. **Trivy SBOM only** - Uses `trivy sbom --format cyclonedx`, not vulnerability scans
5. **Missing tools** - Scan continues but marks tool as `skipped`
6. **No tests** - Verify via API and `logs/tool-output/` output
7. **Webhook signature** - Must match between GitHub and .env

---

## Configuration Checklist

- [x] Python dependencies installed: `pip install -r requirements.txt`
- [x] GitHub App created with required permissions
- [x] `.env` configured with App ID, private key, webhook secret
- [x] ngrok token configured for public webhook access (optional)
- [x] Security tools installed in WSL
- [x] GitHub webhook configured in App settings
- [x] Webhook URL set to: `https://your-ngrok-url.ngrok.io/github/webhook`

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_APP_ID` | Yes | GitHub App ID |
| `GITHUB_APP_NAME` | Yes | GitHub App name |
| `GITHUB_PRIVATE_KEY` | Yes | RSA private key (escaped `\n`) |
| `GITHUB_WEBHOOK_SECRET` | Yes | HMAC secret for webhook verification |
| `NGROK_OAUTH_TOKEN` | No | For auto-creating public tunnel |
| `FLASK_SECRET_KEY` | No | For session security (auto-generated if missing) |

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard |
| `/api/overview` | GET | Dashboard stats |
| `/api/history` | GET | Scan history |
| `/api/history/<scan_id>` | GET | Scan details |
| `/api/repos` | GET | List repositories |
| `/api/repos/scan` | POST | Trigger single scan |
| `/api/repos/scan-all` | POST | Trigger all repos scan |
| `/api/settings` | GET/POST | App settings |
| `/github/webhook` | POST | GitHub webhook receiver |

---

## Operator-Viewer Parent-Child Relationship

The system enforces a strict parent-child hierarchy between Operators and the Viewers they create.

### User Model (`models/database.py`)

The `User` model has a `created_by_id` field (FK → `users.id`) that tracks which user created this user. This creates the parent-child relationship:

```python
creator = db.relationship('User', remote_side='User.id', backref=db.backref('created_users', lazy='dynamic'))
# user.creator → the user who created this user
# user.created_users → users created by this user (e.g., operator.created_users = their viewers)
```

### Role Hierarchy & Scope

| Role | Can create | Sees in user list | Can edit/delete |
|------|-----------|-------------------|-----------------|
| **Admin** | admin, operator, viewer | All users | Any user |
| **Operator** | viewer only | Admins + their own viewers | Only their own viewers |

### FP (False Positive) Routing

When a viewer submits a false positive request, it is routed based on who created them:

1. **Viewer's FP** → Goes to **their parent operator** (the operator who created them via `created_by_id`)
2. **If viewer has no parent operator** → Falls back to the first operator in the DB, then first admin
3. **Operator's FP** → Goes directly to `PENDING_ADMIN` (skips operator review, as before)
4. **Admin's FP** → Immediately `APPROVED_FP` (as before)

### Operator Scoping in FP Flow

- **Review Queue** (`get_fp_review_queue`): Operators see only `PENDING_OPERATOR` FPs from **their own viewers**
- **FP List** (`get_fp_requests`): Operators see FPs from their own viewers by default
- **Pending Count** (`/api/fp/pending-count`): Operators count only their own viewers' pending FPs

### Enforcement Points

- `modules/fp_manager.py:submit_fp_request()` — Assigns viewer FP to `viewer.creator` (their parent operator)
- `modules/fp_manager.py:get_fp_review_queue()` — Filters `PENDING_OPERATOR` by operator's `created_users`
- `modules/fp_manager.py:get_fp_requests()` — Default scope for operators shows their viewers' FPs
- `app/fp_routes.py:fp_pending_count()` — Scopes pending count to operator's viewers
- `app/routes.py:api_get_users()` — Operators see only admins + `created_by_id == current_user.id`
- `app/routes.py:api_update_user()` — Operators can only edit viewers where `created_by_id == current_user.id`
- `app/routes.py:api_delete_user()` — Operators can only delete viewers where `created_by_id == current_user.id`

---

## Auto-Update Feature

On startup, `run.py` automatically checks if a newer version exists on the remote `origin/main`:

1. **Fetch** - Runs `git fetch origin main`
2. **Compare** - Compares local `HEAD` with `origin/main` via `rev-parse`
3. **Prompt** - If behind, shows commit count and asks `[y/N]` to update
4. **Update** - Stashes local changes, pulls latest code, restarts via `os.execv`

Implemented in `run.py:290` - `check_for_updates()` function, called before `create_app()`.

**Edge cases handled:**
- No git available (FileNotFoundError) → silently skip
- No network (TimeoutExpired) → logged warning, continue
- Local changes ahead of remote → info message, no prompt
- Already up-to-date → brief confirmation, no prompt
- Pull failure → log error, continue with current version
- User declines → skip, continue normally