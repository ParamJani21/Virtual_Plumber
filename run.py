#!/usr/bin/env python3
"""
VIRTUAL_PLUMBER Application Runner
Starts ngrok tunnel with .env token and Flask development server
Maintained by ParamJani21
"""

import os
import sys
import signal
import time
import shlex
import subprocess
import json
import requests
from pathlib import Path

# Add parent directory to path for module imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.env_config import env_config
from app import create_app

# Global variables for cleanup
ngrok_process = None
ngrok_tunnel_url = None


def load_env():
    """Load environment variables from .env file"""
    env_vars = env_config.read_env()
    return env_vars


def save_env_var(key, value):
    """Save environment variable to .env file - uses same logic as env_config"""
    current_vars = env_config.read_env()
    current_vars[key] = value
    env_config.write_env(current_vars)


def get_port():
    """Get the configured port from .env, default 5000"""
    env_vars = load_env()
    try:
        return int(env_vars.get('FLASK_PORT', 5000))
    except (ValueError, TypeError):
        return 5000


def check_ngrok_installed():
    """Check if ngrok is installed"""
    try:
        result = subprocess.run(['which', 'ngrok'], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except:
        return False


def install_ngrok():
    """Auto-install ngrok"""
    print("[*] Installing ngrok...")
    try:
        subprocess.run('wget -q -O /tmp/ngrok.tgz https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz && tar -xzf /tmp/ngrok.tgz -C /usr/local/bin && rm /tmp/ngrok.tgz',
                      shell=True, check=True, timeout=30)
        return True
    except:
        try:
            subprocess.run('wget -q -O /usr/local/bin/ngrok https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64 && chmod +x /usr/local/bin/ngrok',
                          shell=True, timeout=30)
            return check_ngrok_installed()
        except:
            return False


def ask_ngrok_setup():
    """Interactive ngrok setup wizard"""
    env_vars = load_env()
    existing_token = env_vars.get('NGROK_OAUTH_TOKEN', '')
    existing_subdomain = env_vars.get('NGROK_SUBDOMAIN', '')

    # Case 1: Token and subdomain both exist - return immediately
    if existing_token and existing_subdomain:
        return existing_token, existing_subdomain

    # Case 2: Token exists but no subdomain - use auto-generated domain
    if existing_token and not existing_subdomain:
        print("[*] Token found, domain will be auto-generated on each run")
        return existing_token, None

    # Case 3: No token - run full wizard
    print("\n[!] NGROK_OAUTH_TOKEN not found")

    # Install ngrok if needed
    if not check_ngrok_installed():
        if not install_ngrok():
            print("[!] Install failed")
            return None, None
        print("[✓] ngrok installed")

    if not check_ngrok_installed():
        print("[!] ngrok not found")
        return None, None

    # Get token
    print("""
[?] GET NGROK TOKEN:
    1. Go to: https://dashboard.ngrok.com/get-started/your-authtoken
    2. Login/Signup to ngrok
    3. Go to "Getting Started" section --> Your Authtoken
    3. Copy your authtoken
    4. Paste it below
""")
    try:
        subprocess.Popen(
            ['xdg-open', 'https://dashboard.ngrok.com/get-started/your-authtoken'],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL
        )
    except:
        pass
    print("[?] Paste token: ", end="")
    token = input().strip()

    if not token:
        print("[!] No token, skipping ngrok")
        return None, None

    # Now create new domain
    return ask_new_domain(token)


def ask_new_domain(token):
    """Ask user to create NEW domain with detailed steps"""
    print("""
╔══════════════════════════════════════════════════════════════════════════╗
║                    🔐 CREATE YOUR NGROK DOMAIN 🔐                        ║
╠══════════════════════════════════════════════════════════════════════════╣
║  ⚠️  IMPORTANT: You MUST create a new domain now!                        ║
║                                                                          ║
║  STEP BY STEP:                                                          ║
║  ─────────────                                                          ║
║  1. Click this link → https://dashboard.ngrok.com/cloud-edge/domains   ║
║  2. Click "New Domain" button (top right)                                ║
║  3. Enter domain name (e.g., my-security-app) in the popup              ║
║  4. Click "Continue" to reserve it                                       ║
║  5. Come back here and enter the prefix (my-security-app)                ║
╚══════════════════════════════════════════════════════════════════════════╝
""")
    try:
        subprocess.Popen(
            ['xdg-open', 'https://dashboard.ngrok.com/cloud-edge/domains'],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL
        )
    except:
        pass
    
    # Save token immediately so it persists even if domain setup is skipped
    save_env_var('NGROK_OAUTH_TOKEN', token)
    
    print("\n[?] Enter your NEW domain (prefix only, or full domain): ", end="")
    subdomain = input().strip()
    
    if not subdomain:
        print("[*] Token saved. Domain will be auto-generated each time.")
        return token, None
    
    # Strip full ngrok domain if user pasted the whole thing
    for suffix in ['.ngrok-free.dev', '.ngrok.app', '.ngrok.io']:
        if subdomain.endswith(suffix):
            subdomain = subdomain[:-len(suffix)]
            break
    
    save_env_var('NGROK_SUBDOMAIN', subdomain)
    print(f"[✓] Saved! Your domain: {subdomain}.ngrok-free.dev\n")

    return token, subdomain


def ask_snyk_setup():
    """Try to grab Snyk token from CLI or prompt user"""
    env_vars = load_env()
    existing = env_vars.get('SNYK_TOKEN', '')
    if existing:
        return existing

    token = None
    print("\n[*] Checking for Snyk token...")

    # Try to get from snyk CLI config (try snyk.cmd on Windows, snyk on Unix)
    snyk_cmd = 'snyk.cmd' if os.name == 'nt' else 'snyk'
    snyk_found = False
    for cmd in [snyk_cmd, 'snyk']:
        try:
            result = subprocess.run(
                [cmd, 'config', 'get', 'api'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                token = result.stdout.strip()
                if token:
                    print(f"[✓] Found Snyk token via `{cmd} config get api`")
                    snyk_found = True
                    break
        except FileNotFoundError:
            continue
        except:
            continue
    if not snyk_found:
        # Also check npm global directory directly
        try:
            npm_prefix = subprocess.run(
                ['npm.cmd' if os.name == 'nt' else 'npm', 'root', '-g'],
                capture_output=True, text=True, timeout=10
            ).stdout.strip()
            if npm_prefix:
                snyk_path = os.path.join(npm_prefix, '..', 'snyk.cmd' if os.name == 'nt' else 'snyk')
                if os.path.exists(snyk_path):
                    result = subprocess.run(
                        [snyk_path, 'config', 'get', 'api'],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        token = result.stdout.strip()
                        print(f"[✓] Found Snyk token via npm global install")
        except:
            pass

    # Try configstore file directly as fallback
    if not token:
        try:
            config_path = os.path.expanduser('~/.config/configstore/snyk.json')
            if os.path.exists(config_path):
                with open(config_path) as f:
                    data = json.load(f)
                token = data.get('api', '')
                if token:
                    print(f"[✓] Found Snyk token from ~/.config/configstore/snyk.json")
        except:
            pass

    if token:
        save_env_var('SNYK_TOKEN', token)
        print("[✓] Snyk token saved to .env")
        return token

    # Prompt user
    print("""
[?] SNYK TOKEN:
    Snyk is used for SAST + SCA scanning.
    1. Go to: https://app.snyk.io/account/api-token
    2. Copy your API token
    3. Paste it below (or press Enter to skip)
""")
    print("[?] Paste Snyk token (or press Enter to skip): ", end="")
    token = input().strip()
    if token:
        save_env_var('SNYK_TOKEN', token)
        print("[✓] Snyk token saved to .env")
    else:
        print("[*] Skipping Snyk setup — can be configured later in Settings page")
    return token


def authenticate_ngrok(token):
    """Authenticate ngrok with the provided token"""
    try:
        print("🔐 Authenticating ngrok with token...")
        result = subprocess.run(
            ['ngrok', 'config', 'add-authtoken', token],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            print("✅ ngrok authentication successful")
            return True
        else:
            print(f"❌ ngrok authentication failed: {result.stderr}")
            return False

    except FileNotFoundError:
        print("❌ ERROR: ngrok command not found")
        return False
    except Exception as e:
        print(f"❌ ERROR: Failed to authenticate ngrok: {str(e)}")
        return False


def start_ngrok_tunnel(port=5000, subdomain=None):
    """Start ngrok tunnel on specified port"""
    global ngrok_process, ngrok_tunnel_url

    # Use provided subdomain or fallback to .env
    if not subdomain:
        env_vars = load_env()
        subdomain = env_vars.get('NGROK_SUBDOMAIN', '')

    try:
        print(f"🚀 Starting ngrok tunnel on port {port}...")

        if subdomain:
            print(f"   Using subdomain: {subdomain}")
            ngrok_process = subprocess.Popen(
                ['ngrok', 'http', f'--url={subdomain}.ngrok-free.dev', str(port), '--log=stdout'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
        else:
            print("   Using random subdomain")
            ngrok_process = subprocess.Popen(
                ['ngrok', 'http', str(port), '--log=stdout'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

        print("   Waiting for tunnel to initialize...")
        time.sleep(3)
        
        try:
            response = requests.get('http://localhost:4040/api/tunnels', timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('tunnels'):
                    for tunnel in data['tunnels']:
                        if tunnel.get('proto') == 'https':
                            ngrok_tunnel_url = tunnel.get('public_url')
        except:
            pass
        
        if ngrok_tunnel_url:
            print(f"✅ ngrok tunnel started successfully!")
            print(f"\n{'='*70}")
            print(f"🌐 Public URL: {ngrok_tunnel_url}")
            print(f"{'='*70}\n")
            return ngrok_process, ngrok_tunnel_url
        else:
            print("⚠️  Could not get tunnel URL yet, but ngrok is running in background")
            return ngrok_process, None

    except FileNotFoundError:
        print("❌ ERROR: ngrok command not found")
        return None, None
    except Exception as e:
        print(f"❌ ERROR: Failed to start ngrok tunnel: {str(e)}")
        return None, None


def cleanup_ngrok():
    """Stop ngrok tunnel"""
    global ngrok_process

    if ngrok_process:
        print("\n🛑 Stopping ngrok tunnel...")
        try:
            ngrok_process.terminate()
            try:
                ngrok_process.wait(timeout=3)
                print("✅ ngrok tunnel stopped")
            except subprocess.TimeoutExpired:
                ngrok_process.kill()
                print("✅ ngrok tunnel killed")
        except Exception as e:
            print(f"⚠️  Error stopping ngrok: {str(e)}")
        finally:
            ngrok_process = None


def signal_handler(signum, frame):
    """Handle Ctrl+C and other signals"""
    print("\n\n🛑 Received interrupt signal...")
    cleanup_ngrok()
    print("👋 Goodbye!")
    sys.exit(0)


def print_startup_info():
    """Print startup information"""
    port = get_port()
    print("\n" + "="*70)
    print(" VIRTUAL_PLUMBER - GitHub Security Scanning Dashboard")
    print("="*70)
    print(f"📝 Environment: Development")
    print(f"🔧 Flask Debug: Enabled")
    print(f"🌐 Local URL: http://localhost:{port}")
    print("="*70 + "\n")


def check_for_updates():
    """Check if a newer version is available on main and offer to update"""
    try:
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        origin_url = subprocess.run(
            ['git', '-C', repo_dir, 'remote', 'get-url', 'origin'],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()

        if not origin_url:
            return False

        print("[*] Checking for updates (origin/main)...")
        subprocess.run(['git', '-C', repo_dir, 'fetch', 'origin', 'main'],
                       capture_output=True, timeout=30)

        local_sha = subprocess.run(
            ['git', '-C', repo_dir, 'rev-parse', 'HEAD'],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()

        remote_sha = subprocess.run(
            ['git', '-C', repo_dir, 'rev-parse', 'origin/main'],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()

        if not local_sha or not remote_sha:
            return False

        if local_sha == remote_sha:
            print("[✓] Already up-to-date\n")
            return False

        behind = subprocess.run(
            ['git', '-C', repo_dir, 'rev-list', '--count', f'{local_sha}..origin/main'],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()

        ahead = subprocess.run(
            ['git', '-C', repo_dir, 'rev-list', '--count', f'origin/main..{local_sha}'],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()

        behind_count = int(behind) if behind else 0
        ahead_count = int(ahead) if ahead else 0

        if behind_count > 0:
            print(f"\n{'='*60}")
            print(f"  Update Available! {behind_count} new commit(s) behind origin/main")
            if ahead_count > 0:
                print(f"  (You have {ahead_count} local commit(s) ahead)")
            print(f"{'='*60}")
            print("[?] Do you want to update? [y/N]: ", end="")
            answer = input().strip().lower()
            if answer in ('y', 'yes'):
                print("[*] Stashing local changes...")
                subprocess.run(['git', '-C', repo_dir, 'stash'], capture_output=True, timeout=10)
                print("[*] Pulling latest code...")
                subprocess.run(['git', '-C', repo_dir, 'fetch', 'origin', 'main'],
                               capture_output=True, timeout=30)
                result = subprocess.run(['git', '-C', repo_dir, 'reset', '--hard', 'origin/main'],
                                        capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    print("[✓] Updated successfully! Restarting...\n")
                    return True
                else:
                    print(f"[!] Update failed: {result.stderr}")
                    print("[!] Continuing with current version")
            else:
                print("[*] Skipping update\n")
        elif ahead_count > 0:
            print(f"[*] You are {ahead_count} commit(s) ahead of origin/main (local changes)\n")
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        print("[!] Update check timed out (no network)?")
    except Exception as e:
        print(f"[!] Update check failed: {e}")
    return False


def prompt_port(port):
    """Always ask user if they want to use the current port or change it"""
    while True:
        print(f"\n[?] Use port {port}? [Y/n]: ", end="")
        answer = input().strip().lower()
        if answer in ('', 'y', 'yes'):
            # Check if port is actually free
            try:
                pids = subprocess.run(f'lsof -ti:{shlex.quote(str(port))}', shell=True, capture_output=True, text=True, timeout=5).stdout.strip()
                if pids:
                    proc_names = []
                    for pid in pids.splitlines():
                        name = subprocess.run(f'ps -p {shlex.quote(pid)} -o comm=', shell=True, capture_output=True, text=True, timeout=5).stdout.strip()
                        proc_names.append(f"{name} (PID {pid})")
                    print(f"\n[!] Port {port} is already in use by: {', '.join(proc_names)}")
                    print("[?] What would you like to do?")
                    print(f"  1) Kill the existing process(es) and use port {port}")
                    print("  2) Use a different port")
                    choice = input("[?] Enter 1 or 2: ").strip()
                    if choice == '1':
                        for pid in pids.splitlines():
                            subprocess.run(f'kill -9 {shlex.quote(pid)}', shell=True, timeout=5)
                        print(f"[✓] Process(es) on port {port} killed\n")
                        return port
                    elif choice == '2':
                        pass
                    else:
                        print("[!] Invalid choice\n")
                        continue
                else:
                    return port
            except:
                return port
        elif answer in ('n', 'no'):
            pass
        else:
            print("[!] Enter y or n")
            continue

        # Ask for new port
        while True:
            new_port = input("[?] Enter new port number (1024-65535): ").strip()
            if new_port.isdigit() and 1024 <= int(new_port) <= 65535:
                save_env_var('FLASK_PORT', new_port)
                port = int(new_port)
                print(f"[✓] Port changed to {port}\n")
                return port
            else:
                print("[!] Invalid port. Enter a number between 1024-65535.")


def main():
    """Main entry point"""

    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    port = get_port()
    print_startup_info()

    # Always ask user about the port
    print(f"[*] Checking port {port}...")
    port = prompt_port(port)

    # Check for updates before any interactive prompts
    print("="*70)
    if check_for_updates():
        print("[*] Restarting with updated code...\n")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    # Snyk token setup - try to grab from snyk CLI config if available
    snyk_token = ask_snyk_setup()

    # ngrok setup
    ngrok_token, ngrok_subdomain = ask_ngrok_setup()

    if ngrok_token:
        if authenticate_ngrok(ngrok_token):
            process, url = start_ngrok_tunnel(port=port, subdomain=ngrok_subdomain)
            if url:
                webhook_url = f"{url}/github/webhook"
                print(f"\n{'='*70}")
                print(f"[*] Webhook: {webhook_url}")
                print(f"\n{'='*70}")

                # Check if GitHub credentials already exist
                env_vars = load_env()
                if env_vars.get('GITHUB_APP_ID') and env_vars.get('GITHUB_SECRET_KEY') and env_vars.get('GITHUB_WEBHOOK_SECRET'):
                    print("[✓] GitHub App already configured\n")
                else:
                    # Setup GitHub App
                    app_setup_url = f'https://github.com/settings/apps/new?name=VIRTUAL_PLUMBER&description=Security+Scanning+Dashboard&url={url}&hook_active=true&hook_url={webhook_url}'
                    print(f"""
{'='*70}
[?] SETUP GITHUB APP:
{'='*70}

STEP 1: Create a GitHub App
   URL -> {app_setup_url}

   In the GitHub App creation page:
   - Find "Webhook URL" and paste: {webhook_url}
   - Set "Webhook secret" to a secret of your choice (remember it!)
   - Under "Repository Permissions" set:
       - Checks: Read & Write
       - Commit statuses: Read & Write
       - Contents: Read
       - Pull requests: Read & Write
   - Under "Subscribe to events" check: Pull requests

STEP 2: After creating the app
   - Download the private key (.pem file)
   - Note the App ID (shown at the top of the app page)
   - Install the app on your org/repos

{'='*70}
""")
                    print("[?] Press ENTER to open the GitHub App creation page in your browser")
                    print("    (or Ctrl+C to skip and enter the URL manually)")
                    input()
                    try:
                        if sys.platform == 'win32':
                            subprocess.Popen(['start', app_setup_url], shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                        else:
                            subprocess.Popen(['xdg-open', app_setup_url], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                    except:
                        pass
                    print("[?] Press ENTER once you have created the GitHub App and have the App ID + private key ready...")
                    input()

                    # Ask for GitHub App credentials
                    print("\n[?] Enter GitHub App ID: ", end="")
                    app_id = input().strip()

                    # Read private key from file path
                    while True:
                        print("[?] Path to private key (.pem file): ", end="")
                        pem_path = input().strip()
                        if pem_path and os.path.exists(pem_path):
                            with open(pem_path, 'r') as f:
                                private_key = f.read().strip()
                            break
                        elif pem_path:
                            print("[!] File not found, try again")
                        else:
                            print("[!] Enter path to .pem file")

                    print("[?] Enter webhook secret (same as in GitHub): ", end="")
                    webhook_secret = input().strip()

                    if app_id and private_key and webhook_secret:
                        save_env_var('GITHUB_APP_ID', app_id)
                        save_env_var('GITHUB_APP_NAME', 'VIRTUAL_PLUMBER')
                        # Pass raw newlines - write_env will escape and quote
                        save_env_var('GITHUB_SECRET_KEY', private_key)
                        save_env_var('GITHUB_WEBHOOK_SECRET', webhook_secret)
                        print("[✓] GitHub App credentials saved\n")

    print("="*70)
    print(f"Starting Flask (http://localhost:{port})... Ctrl+C to stop")
    print("    ℹ If on a VPS, use your public IP and whitelist the domain for webhook access")
    print("="*70 + "\n")

    try:
        app = create_app()

        # Check if default admin credentials should be shown
        with app.app_context():
            from models.database import User
            if not User.query.filter_by(role='admin').first():
                print("\n" + "="*70)
                print("  FIRST TIME SETUP")
                print("="*70)
                print("  Default Admin Credentials:")
                print("    Username: admin")
                print("    Password: Securepass123@#")
                print("  Please change the password after first login.")
                print("="*70 + "\n")

        app.run(
            host='0.0.0.0',
            port=port,
            debug=True,
            use_reloader=False
        )

    except KeyboardInterrupt:
        print("\n\n🛑 Interrupted...")
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()

    finally:
        cleanup_ngrok()
        print("👋 Application stopped")
        sys.exit(0)


if __name__ == '__main__':
    main()