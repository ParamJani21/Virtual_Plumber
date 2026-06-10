"""
Control APIs Module - Repository Cloning & Scanning Control
Handles Git operations using GitHub App authentication and WSL execution
"""

import os
import subprocess
import shlex
import logging
import json
import shutil
import uuid
import time
from pathlib import Path
from datetime import datetime
from modules.repos import get_installation_token, get_installations, get_repositories

logger = logging.getLogger(__name__)


def get_tmp_directory():
    """
    Get the /tmp directory path in VIRTUAL_PLUMBER root
    
    Returns:
        Path to /tmp directory
    """
    try:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tmp_dir = os.path.join(root_dir, 'tmp')
        
        # Ensure tmp directory exists
        os.makedirs(tmp_dir, exist_ok=True)
        logger.info(f'✓ TMP directory ready: {tmp_dir}')
        return tmp_dir
    except Exception as e:
        logger.exception(f'Error creating tmp directory: {e}')
        return None


def get_wsl_path(windows_path):
    """
    Convert Windows path to WSL path
    Example: C:\\Users\\user\\project -> /mnt/c/Users/user/project
    
    Args:
        windows_path: Windows file path
    
    Returns:
        WSL path string
    """
    try:
        # Normalize the path
        windows_path = os.path.normpath(windows_path)
        
        # If path contains drive letter (C:, D:, etc)
        if len(windows_path) > 1 and windows_path[1] == ':':
            drive = windows_path[0].lower()
            rest = windows_path[2:].replace('\\', '/')
            wsl_path = f'/mnt/{drive}{rest}'
            logger.debug(f'Converted Windows path to WSL: {windows_path} -> {wsl_path}')
            return wsl_path
        else:
            # Already a Unix-like path
            logger.debug(f'Path is already Unix-like: {windows_path}')
            return windows_path
    except Exception as e:
        logger.exception(f'Error converting path to WSL format: {e}')
        return windows_path


def run_wsl_command(command, cwd=None, timeout=300):
    """
    Execute a command - works on Linux (direct) or Windows+WSL
    
    Args:
        command: Command string to execute
        cwd: Current working directory
        timeout: Command timeout in seconds (default: 300 for git clone, can be 600 for scans)
    
    Returns:
        Tuple of (success: bool, stdout: str, stderr: str)
    """
    try:
        logger.info(f'[WSL] Executing command: {command}')
        if cwd:
            logger.info(f'[WSL] Working directory: {cwd}')
        
        # Check if WSL is available, otherwise run directly on Linux
        wsl_available = False
        try:
            result = subprocess.run(
                ['which', 'wsl'],
                capture_output=True,
                text=True,
                timeout=5
            )
            wsl_available = result.returncode == 0
        except Exception:
            pass
        
        if wsl_available:
            # Use WSL on Windows
            cmd_list = ['wsl', '-e', 'bash', '-c', command]
            logger.debug(f'[WSL] Running via WSL: {cmd_list}')
        else:
            # Run directly on Linux (no WSL needed)
            cmd_list = ['bash', '-c', command]
            logger.debug(f'[WSL] Running directly (no WSL): {cmd_list}')
        
        # Execute the command
        result = subprocess.run(
            cmd_list,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        success = result.returncode == 0
        stdout = result.stdout
        stderr = result.stderr
        
        if success:
            logger.info(f'[WSL] ✓ Command succeeded (exit code: {result.returncode})')
            logger.debug(f'[WSL] stdout: {stdout[:500]}')
        else:
            logger.error(f'[WSL] ✗ Command failed (exit code: {result.returncode})')
            logger.error(f'[WSL] stderr: {stderr[:500]}')
        
        return success, stdout, stderr
    
    except subprocess.TimeoutExpired:
        logger.error('[WSL] ✗ Command timed out (5 minutes)')
        return False, '', 'Command timed out after 300 seconds'
    except Exception as e:
        logger.exception(f'[WSL] Exception executing command: {e}')
        return False, '', str(e)


def get_repo_installation_id(repo_owner, repo_name):
    """
    Find the installation ID for a specific repository
    
    Args:
        repo_owner: Repository owner/organization
        repo_name: Repository name
    
    Returns:
        Installation ID or None
    """
    try:
        logger.info(f'Finding installation ID for {repo_owner}/{repo_name}...')
        
        repos = get_repositories()
        logger.debug(f'Fetched {len(repos)} total repositories')
        
        for repo in repos:
            if repo.get('owner') == repo_owner and repo.get('name') == repo_name:
                # We need to find the right installation
                # For now, we'll use the first installation and hope it works
                # In a real scenario, we'd track which installation manages which repo
                installations = get_installations()
                if installations:
                    installation_id = installations[0]
                    logger.info(f'✓ Found installation ID: {installation_id}')
                    return installation_id
        
        # If exact match not found, try first installation
        installations = get_installations()
        if installations:
            logger.warning(f'Repository not found in exact match, using first installation')
            return installations[0]
        
        logger.error(f'No installations found for {repo_owner}/{repo_name}')
        return None
    
    except Exception as e:
        logger.exception(f'Error finding installation ID: {e}')
        return None


def cleanup_directory_force(path, retries=3):
    """
    Forcefully remove a directory, handling Windows file locks
    
    Args:
        path: Directory path to remove
        retries: Number of retry attempts
    
    Returns:
        True if successful, False otherwise
    """
    try:
        logger.debug(f'[Cleanup] Attempting to forcefully remove: {path}')
        
        for attempt in range(retries):
            try:
                # Try using shutil first
                shutil.rmtree(path)
                logger.info(f'[Cleanup] ✓ Removed directory (attempt {attempt + 1})')
                return True
            except PermissionError as e:
                logger.warning(f'[Cleanup] Permission denied on attempt {attempt + 1}, retrying...')
                
                if attempt < retries - 1:
                    import time
                    time.sleep(0.5)  # Short delay before retry
                    continue
                
                # Last attempt: try using Windows command
                try:
                    logger.info('[Cleanup] Attempting Windows rmdir command...')
                    result = subprocess.run(
                        ['cmd', '/c', 'rmdir', '/s', '/q', path],
                        capture_output=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        logger.info('[Cleanup] ✓ Removed directory using Windows command')
                        return True
                except Exception as e2:
                    logger.warning(f'[Cleanup] Windows command also failed: {e2}')
                
                raise
    
    except Exception as e:
        logger.error(f'[Cleanup] Failed to remove directory: {e}')
        return False


def clone_repository(repo_id, repo_name, repo_owner, repo_url, repo_branch='main', scan_id=None):
    """
    Clone a GitHub repository using GitHub App authentication
    Runs git clone in WSL and stores in /tmp directory
    
    Args:
        repo_id: Repository ID
        repo_name: Repository name
        repo_owner: Repository owner
        repo_url: Repository HTTPS URL
        repo_branch: Branch to clone (default: main)
        scan_id: Unique scan ID to avoid path clashes on concurrent scans
    
    Returns:
        Dict with status and details
    """
    try:
        logger.debug('=' * 80)
        logger.debug(f'🔍 CLONE REQUEST: {repo_owner}/{repo_name} (ID: {repo_id})')
        logger.debug(f'   Branch: {repo_branch}')
        logger.debug(f'   URL: {repo_url}')
        logger.debug(f'   Scan ID: {scan_id or "N/A"}')
        logger.debug('=' * 80)
        
        # Get tmp directory
        tmp_dir = get_tmp_directory()
        if not tmp_dir:
            logger.error('Failed to get tmp directory')
            return {
                'status': 'error',
                'message': 'Failed to initialize tmp directory',
                'repo_id': repo_id,
                'repo_name': repo_name
            }
        
        # Create scan-unique directory to avoid clashes on concurrent scans
        if scan_id:
            repo_dir = os.path.join(tmp_dir, scan_id, repo_owner, repo_name)
        else:
            repo_dir = os.path.join(tmp_dir, repo_owner, repo_name)
        logger.info(f'📁 Clone destination: {repo_dir}')
        
        # Get installation token for authentication
        logger.info('[Auth] Getting GitHub App installation token...')
        installation_id = get_repo_installation_id(repo_owner, repo_name)
        
        if not installation_id:
            logger.error('[Auth] Failed to get installation ID')
            return {
                'status': 'error',
                'message': 'Failed to get GitHub App installation ID',
                'repo_id': repo_id,
                'repo_name': repo_name
            }
        
        logger.debug(f'[Auth] Installation ID: {installation_id}')
        
        installation_token = get_installation_token(installation_id)
        if not installation_token:
            logger.error('[Auth] Failed to get installation token')
            return {
                'status': 'error',
                'message': 'Failed to get GitHub App installation token',
                'repo_id': repo_id,
                'repo_name': repo_name
            }
        
        logger.info(f'[Auth] ✓ Got installation token (first 20 chars): {installation_token[:20]}...')
        
        # Construct authenticated URL with token
        # Format: https://x-access-token:TOKEN@github.com/owner/repo.git
        if '@' in repo_url:
            # URL might already have auth, strip it
            repo_url = repo_url.split('@')[1]
            if repo_url.startswith('//'):
                repo_url = repo_url[2:]
        
        authenticated_url = f'https://x-access-token:{installation_token}@github.com/{repo_owner}/{repo_name}.git'
        logger.debug(f'[Auth] Authenticated URL prepared (token hidden)')
        
        # Convert paths for WSL
        wsl_repo_dir = get_wsl_path(repo_dir)
        logger.info(f'[WSL] WSL path: {wsl_repo_dir}')
        
        # Clean up existing clone if it exists
        logger.info('[Clone] Checking for existing clone...')
        if os.path.exists(repo_dir):
            logger.warning(f'[Clone] Directory already exists, cleaning up: {repo_dir}')
            if not cleanup_directory_force(repo_dir):
                logger.error('[Clone] Failed to clean existing directory')
                return {
                    'status': 'error',
                    'message': f'Failed to clean existing repository - directory locked or in use',
                    'repo_id': repo_id,
                    'repo_name': repo_name
                }
            logger.info('[Clone] ✓ Cleaned up existing directory')
        
        # Prepare parent directory
        os.makedirs(repo_dir, exist_ok=True)
        parent_path = os.path.join(tmp_dir, scan_id, repo_owner) if scan_id else os.path.join(tmp_dir, repo_owner)
        wsl_parent_dir = get_wsl_path(parent_path)
        logger.info(f'[Clone] Creating parent directory: {wsl_parent_dir}')
        mkdir_cmd = f'mkdir -p {shlex.quote(wsl_parent_dir)}'
        success, stdout, stderr = run_wsl_command(mkdir_cmd)
        if not success:
            logger.error('[Clone] Failed to create parent directory')
            return {
                'status': 'error',
                'message': f'Failed to create directory: {stderr}',
                'repo_id': repo_id,
                'repo_name': repo_name
            }
        
        logger.info('[Clone] ✓ Parent directory ready')
        
        # Clone the repository
        logger.info(f'[Clone] Starting git clone...')
        logger.info(f'[Clone] Cloning from: {repo_owner}/{repo_name}')
        logger.info(f'[Clone] Branch: {repo_branch}')
        
        clone_cmd = (
            f'git clone '
            f'--branch {shlex.quote(repo_branch)} '
            f'--depth 1 '
            f'--single-branch '
            f'{shlex.quote(authenticated_url)} '
            f'{shlex.quote(wsl_repo_dir)}'
        )
        
        logger.debug(f'[Clone] Git command (token hidden): '
                    f'git clone --branch {repo_branch} --depth 1 --single-branch '
                    f'https://x-access-token:***@github.com/{repo_owner}/{repo_name}.git {wsl_repo_dir}')
        
        success, stdout, stderr = run_wsl_command(clone_cmd)
        
        if not success:
            logger.error('[Clone] ✗ Git clone failed')
            logger.error(f'[Clone] Error: {stderr}')
            return {
                'status': 'error',
                'message': f'Git clone failed: {stderr}',
                'repo_id': repo_id,
                'repo_name': repo_name,
                'error_details': stderr[:500]
            }
        
        logger.info('[Clone] ✓ Git clone completed successfully')
        logger.info(f'[Clone] stdout: {stdout[:300]}')
        
        # Verify clone
        logger.info('[Clone] Verifying cloned repository...')
        verify_cmd = f'ls -la {shlex.quote(wsl_repo_dir)}'
        success, stdout, stderr = run_wsl_command(verify_cmd)
        
        if success:
            logger.info('[Clone] ✓ Repository verified')
            logger.info(f'[Clone] Contents: {stdout[:300]}')
        else:
            logger.warning('[Clone] ⚠ Failed to verify repository')
        
        # Get clone details
        logger.info('[Clone] Gathering clone details...')
        details_cmd = f'cd {shlex.quote(wsl_repo_dir)} && git log -1 --format="%H %s %ai"'
        success, commit_info, _ = run_wsl_command(details_cmd)
        
        clone_info = {
            'repo_id': repo_id,
            'repo_name': repo_name,
            'repo_owner': repo_owner,
            'repo_url': repo_url,
            'branch': repo_branch,
            'clone_path': repo_dir,
            'wsl_path': wsl_repo_dir,
            'cloned_at': datetime.now().isoformat(),
            'commit_info': commit_info.strip() if success else 'Unknown'
        }
        
        logger.debug('=' * 80)
        logger.debug(f'✅ CLONE SUCCESSFUL: {repo_owner}/{repo_name}')
        logger.debug(f'   Path: {repo_dir}')
        logger.debug(f'   Branch: {repo_branch}')
        logger.debug(f'   Commit: {clone_info["commit_info"][:50]}...' if len(clone_info.get('commit_info', '')) > 50 else f'   Commit: {clone_info.get("commit_info")}')
        logger.debug('=' * 80)
        
        return {
            'status': 'success',
            'message': f'Successfully cloned {repo_owner}/{repo_name}',
            'repo_id': repo_id,
            'repo_name': repo_name,
            'repo_owner': repo_owner,
            'clone_details': clone_info
        }
    
    except Exception as e:
        logger.exception(f'Exception in clone_repository: {e}')
        return {
            'status': 'error',
            'message': f'Exception during clone: {str(e)}',
            'repo_id': repo_id,
            'repo_name': repo_name,
            'error_details': str(e)
        }


def get_cloned_repos():
    """
    Get list of all cloned repositories in /tmp
    
    Returns:
        List of cloned repository info
    """
    try:
        logger.info('[List] Getting list of cloned repositories...')
        
        tmp_dir = get_tmp_directory()
        if not tmp_dir:
            logger.error('[List] Failed to get tmp directory')
            return []
        
        cloned_repos = []
        
        if not os.path.exists(tmp_dir):
            logger.warning(f'[List] Tmp directory does not exist: {tmp_dir}')
            return []
        
        # Walk through directory structure: /tmp/owner/repo_name
        for owner in os.listdir(tmp_dir):
            owner_path = os.path.join(tmp_dir, owner)
            
            if not os.path.isdir(owner_path):
                continue
            
            logger.debug(f'[List] Scanning owner: {owner}')
            
            for repo_name in os.listdir(owner_path):
                repo_path = os.path.join(owner_path, repo_name)
                
                if not os.path.isdir(repo_path):
                    continue
                
                try:
                    # Get git info if possible
                    git_dir = os.path.join(repo_path, '.git')
                    is_git = os.path.exists(git_dir)
                    
                    # Get directory size
                    total_size = 0
                    for dirpath, dirnames, filenames in os.walk(repo_path):
                        for f in filenames:
                            fp = os.path.join(dirpath, f)
                            if os.path.exists(fp):
                                total_size += os.path.getsize(fp)
                    
                    # Get commit info
                    commit_info = 'Unknown'
                    if is_git:
                        try:
                            result = subprocess.run(
                                ['git', '-C', repo_path, 'log', '-1', '--format=%H %s'],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )
                            if result.returncode == 0:
                                commit_info = result.stdout.strip()
                        except Exception as e:
                            logger.debug(f'[List] Failed to get git info for {owner}/{repo_name}: {e}')
                    
                    repo_info = {
                        'owner': owner,
                        'name': repo_name,
                        'path': repo_path,
                        'is_git': is_git,
                        'size_bytes': total_size,
                        'size_mb': round(total_size / (1024 * 1024), 2),
                        'commit': commit_info,
                        'created_at': datetime.fromtimestamp(
                            os.path.getctime(repo_path)
                        ).isoformat()
                    }
                    
                    cloned_repos.append(repo_info)
                    logger.debug(f'[List] Found cloned repo: {owner}/{repo_name} ({repo_info["size_mb"]}MB)')
                
                except Exception as e:
                    logger.warning(f'[List] Error processing {owner}/{repo_name}: {e}')
                    continue
        
        logger.info(f'[List] ✓ Found {len(cloned_repos)} cloned repositories')
        return cloned_repos
    
    except Exception as e:
        logger.exception(f'[List] Exception in get_cloned_repos: {e}')
        return []


def cleanup_cloned_repo(repo_owner, repo_name, scan_id=None):
    """
    Remove a cloned repository from /tmp
    
    Args:
        repo_owner: Repository owner
        repo_name: Repository name
        scan_id: Scan ID for scan-unique directory (optional)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        logger.debug('=' * 80)
        logger.debug(f'🗑️  CLEANUP REQUEST: {repo_owner}/{repo_name} (scan_id={scan_id or "N/A"})')
        logger.debug('=' * 80)
        
        tmp_dir = get_tmp_directory()
        if not tmp_dir:
            logger.error('[Cleanup] Failed to get tmp directory')
            return False
        
        if scan_id:
            repo_path = os.path.join(tmp_dir, scan_id, repo_owner, repo_name)
        else:
            repo_path = os.path.join(tmp_dir, repo_owner, repo_name)
        logger.info(f'[Cleanup] Target path: {repo_path}')
        
        if not os.path.exists(repo_path):
            logger.warning(f'[Cleanup] ⚠ Path does not exist: {repo_path}')
            return False
        
        if not os.path.isdir(repo_path):
            logger.error(f'[Cleanup] ✗ Path is not a directory: {repo_path}')
            return False
        
        try:
            logger.info(f'[Cleanup] Removing directory...')
            
            # Define error handler for Windows file permission issues on git files
            def handle_remove_error(func, path, exc_info):
                """Error handler for shutil.rmtree that handles Windows file locks"""
                import stat
                exc_type, exc_val, exc_tb = exc_info
                if exc_type and (exc_type == PermissionError or exc_type == OSError):
                    try:
                        logger.debug(f'[Cleanup] Fixing permissions on: {path}')
                        # Make file writable and try again
                        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                        func(path)
                        logger.debug(f'[Cleanup] Successfully deleted after chmod: {path}')
                    except Exception as e:
                        logger.warning(f'[Cleanup] Could not fix permissions on {path}: {e}')
                else:
                    logger.error(f'[Cleanup] Unexpected error removing {path}: {exc_val}')
            
            # Remove directory with error handler for permission issues
            shutil.rmtree(repo_path, onerror=handle_remove_error)
            logger.info(f'[Cleanup] ✓ Successfully removed: {repo_path}')
            
            # Try to clean up empty owner directory
            owner_path = os.path.join(tmp_dir, repo_owner)
            if os.path.exists(owner_path) and len(os.listdir(owner_path)) == 0:
                logger.info(f'[Cleanup] Removing empty owner directory: {owner_path}')
                os.rmdir(owner_path)
                logger.info(f'[Cleanup] ✓ Removed empty owner directory')
            
            logger.debug('=' * 80)
            logger.debug(f'✅ CLEANUP SUCCESSFUL: {repo_owner}/{repo_name}')
            logger.debug('=' * 80)
            return True
        
        except Exception as e:
            logger.exception(f'[Cleanup] Exception removing directory: {e}')
            return False
    
    except Exception as e:
        logger.exception(f'[Cleanup] Exception in cleanup_cloned_repo: {e}')
        return False


def get_logs_directory():
    """
    Get the logs directory path
    
    Returns:
        Path to logs directory
    """
    try:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logs_dir = os.path.join(root_dir, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        return logs_dir
    except Exception as e:
        logger.exception(f'Error getting logs directory: {e}')
        return None


def generate_scan_id():
    """
    Generate a unique scan ID
    
    Returns:
        Unique scan ID string
    """
    return str(uuid.uuid4())


def run_opengrep_scan(repo_path, scan_id):
    """
    Run OpenGrep scan on repository using WSL
    
    Args:
        repo_path: Path to cloned repository
        scan_id: Unique scan identifier
    
    Returns:
        Tuple of (success: bool, scan_results: dict)
    """
    try:
        logger.debug('=' * 80)
        logger.debug(f'🔍 OPENGREP SCAN: {scan_id}')
        logger.debug(f'   Repository: {repo_path}')
        logger.debug('=' * 80)
        
        # Convert path for WSL
        wsl_repo_path = get_wsl_path(repo_path)
        logger.info(f'[OpenGrep] WSL path: {wsl_repo_path}')
        
        # Check if `opengrep` is available in WSL
        logger.debug('[OpenGrep] Checking for opengrep availability in WSL...')
        check_tool_cmd = 'command -v opengrep || true'
        success, tool_path, stderr = run_wsl_command(check_tool_cmd)

        tool_name = None
        if success and tool_path and tool_path.strip():
            tool_path = tool_path.strip().splitlines()[0]
            tool_name = os.path.basename(tool_path)
            logger.info(f'[OpenGrep] ✓ Found tool: {tool_name} at {tool_path}')
        else:
            logger.error('[OpenGrep] ✗ opengrep not found in WSL PATH')
            return False, {
                'error': 'opengrep not found',
                'message': 'Please install opengrep in WSL and ensure it is in PATH',
                'scan_id': scan_id
            }

        # Run scan with the discovered tool
        logger.debug('[OpenGrep] Starting scan...')
        logger.debug('[OpenGrep] Scanning all file types in repository...')

        # Build scan command - use auto or scan without specific configs
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        rules_dir = os.path.join(project_root, 'rules', 'semgrep-rules')
        rules_path = get_wsl_path(rules_dir)

        opengrep_cmd = (
            f'cd {shlex.quote(wsl_repo_path)} && '
            f"{tool_name} --json "
            f"--config={rules_path}/generic "
            f"--config={rules_path}/javascript "
            f"--config={rules_path}/python "
            f"--config={rules_path}/java "
            f"--config={rules_path}/go "
            f'. || true'
        )

        logger.debug(f'[OpenGrep] Command: {opengrep_cmd}')
        
        success, stdout, stderr = run_wsl_command(opengrep_cmd, timeout=600)
        
        if not success and not stdout:
            logger.warning(f'[OpenGrep] ⚠ Scan command had issues, but continuing...')

        if stderr and stderr.strip():
            logger.debug(f'[OpenGrep] stderr: {stderr[:2000]}')

        logger.debug('[OpenGrep] ✓ Scan completed')

        # Build base results structure
        scan_results = {
            'scan_id': scan_id,
            'timestamp': datetime.now().isoformat(),
            'repository': os.path.basename(repo_path),
            'raw_output': stdout,
            'status': 'completed'
        }

        # Parse JSON output robustly: try full-document parse, then line-based fallback
        findings = []
        try:
            if stdout and stdout.strip():
                try:
                    parsed = json.loads(stdout)
                    # opengrep may return a dict with 'results' or a list
                    if isinstance(parsed, dict) and 'results' in parsed:
                        findings = parsed.get('results', []) or []
                    elif isinstance(parsed, list):
                        findings = parsed
                    else:
                        # Unexpected top-level structure; try line-wise parsing next
                        findings = []
                except Exception:
                    # Fallback: attempt to decode JSON objects from individual lines
                    json_lines = []
                    for line in stdout.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            json_lines.append(obj)
                        except Exception:
                            continue
                    findings = json_lines
            else:
                findings = []
        except Exception as e:
            logger.warning(f'[OpenGrep] Error parsing JSON output: {e}')
            findings = []

        scan_results['results'] = findings
        scan_results['findings_count'] = len(findings)

        if findings:
            logger.info(f'[OpenGrep] ✓ Found {len(findings)} potential issues')
        else:
            logger.info('[OpenGrep] ✓ No issues found')

        logger.info('=' * 80)
        logger.info(f'✅ OPENGREP SCAN COMPLETE: {scan_id}')
        logger.info(f'   Findings: {scan_results.get("findings_count", 0)}')
        logger.info('=' * 80)

        return True, scan_results
    
    except Exception as e:
        logger.exception(f'Exception in run_opengrep_scan: {e}')
        return False, {
            'error': str(e),
            'scan_id': scan_id,
            'status': 'failed'
        }


def run_truffle_scan(repo_path, scan_id):
    """
    Run TruffleHog secret scanning on repository using WSL
    """
    try:
        logger.debug('=' * 80)
        logger.debug(f'🔍 TRUFFLEHOG SCAN (SECRETS): {scan_id}')
        logger.debug(f'   Repository: {repo_path}')
        logger.debug('=' * 80)
        
        wsl_repo_path = get_wsl_path(repo_path)
        logger.info(f'[TruffleHog] WSL path: {wsl_repo_path}')
        
        # Check if TruffleHog is available
        logger.info('[TruffleHog] Checking for trufflehog availability...')
        check_cmd = 'command -v trufflehog || true'
        success, tool_path, stderr = run_wsl_command(check_cmd)
        
        if not (success and tool_path and tool_path.strip()):
            logger.warning('[TruffleHog] ✗ TruffleHog not found - skipping')
            return True, {
                'scan_id': scan_id,
                'timestamp': datetime.now().isoformat(),
                'repository': os.path.basename(repo_path),
                'status': 'skipped',
                'message': 'TruffleHog not installed',
                'results': [],
                'findings_count': 0
            }
        
        logger.debug(f'[TruffleHog] ✓ Found at {tool_path.strip()}')
        logger.debug('[TruffleHog] Starting secret scanning...')
        
        trufflehog_cmd = (
            f'cd {shlex.quote(wsl_repo_path)} && '
            f'trufflehog filesystem . '
            f'--json '
            f'--no-update '
            f'|| true'
        )
        
        success, stdout, stderr = run_wsl_command(trufflehog_cmd, timeout=600)
        logger.debug('[TruffleHog] ✓ Scan completed')
        
        # Parse JSON output
        secrets = []
        try:
            if stdout and stdout.strip():
                json_lines = []
                for line in stdout.splitlines():
                    line = line.strip()
                    if line and line.startswith('{'):
                        try:
                            obj = json.loads(line)
                            if 'DetectorType' in obj:
                                json_lines.append(obj)
                        except:
                            continue
                secrets = json_lines
        except Exception as e:
            logger.warning(f'[TruffleHog] Error parsing output: {e}')
        
        scan_results = {
            'scan_id': scan_id,
            'timestamp': datetime.now().isoformat(),
            'repository': os.path.basename(repo_path),
            'raw_output': stdout,
            'status': 'completed',
            'results': secrets,
            'findings_count': len(secrets)
        }
        
        logger.info(f'[TruffleHog] ✓ Found {len(secrets)} secrets')
        logger.info('=' * 80)
        
        return True, scan_results
    
    except Exception as e:
        logger.exception(f'Exception in run_truffle_scan: {e}')
        return False, {
            'error': str(e),
            'scan_id': scan_id,
            'status': 'error',
            'results': [],
            'findings_count': 0
        }


def run_trivy_scan(repo_path, scan_id):
    """
    Run Trivy security scan on repository using WSL
    
    Args:
        repo_path: Path to cloned repository
        scan_id: Unique scan identifier
    
    Returns:
        Tuple of (success: bool, scan_results: dict)
    """
    try:
        logger.debug('=' * 80)
        logger.debug(f'🔐 TRIVY SCAN: {scan_id}')
        logger.debug(f'   Repository: {repo_path}')
        logger.debug('=' * 80)
        
        # Convert path for WSL
        wsl_repo_path = get_wsl_path(repo_path)
        logger.info(f'[Trivy] WSL path: {wsl_repo_path}')
        
        # Check if Trivy is available in WSL
        logger.info('[Trivy] Checking for trivy availability in WSL...')
        check_tool_cmd = 'command -v trivy || true'
        success, tool_path, stderr = run_wsl_command(check_tool_cmd)

        if not (success and tool_path and tool_path.strip()):
            logger.warning('[Trivy] ✗ Trivy not found in WSL PATH - skipping Trivy scan')
            return True, {
                'scan_id': scan_id,
                'timestamp': datetime.now().isoformat(),
                'repository': os.path.basename(repo_path),
                'status': 'skipped',
                'message': 'Trivy not installed',
                'results': [],
                'findings_count': 0
            }
        
        logger.info(f'[Trivy] ✓ Found trivy at {tool_path.strip()}')

        # Run Trivy SBOM scan only - no vulnerability scanning
        logger.debug('[Trivy] Starting SBOM scan (no vulnerability scan)...')

        trivy_cmd = (
            f'cd {shlex.quote(wsl_repo_path)} && '
            f'trivy fs '
            f'--scanners vuln '
            f'--format json '
            f'--quiet '
            f'. || true'
        )

        logger.debug(f'[Trivy] Command: {trivy_cmd}')
        
        success, stdout, stderr = run_wsl_command(trivy_cmd, timeout=600)
        
        if not success and not stdout:
            logger.warning(f'[Trivy] ⚠ Scan command had issues, but continuing...')
            logger.warning(f'[Trivy] stderr: {stderr[:500]}')
        
        logger.debug('[Trivy] ✓ Scan completed')

        # Build base results structure
        scan_results = {
            'scan_id': scan_id,
            'timestamp': datetime.now().isoformat(),
            'repository': os.path.basename(repo_path),
            'raw_output': stdout,
            'status': 'completed'
        }

        # Parse vulnerability output
        vulnerabilities = []
        try:
            if stdout and stdout.strip():
                try:
                    lines = stdout.strip().split('\n')
                    json_start = 0
                    for i, line in enumerate(lines):
                        if line.strip().startswith('{'):
                            json_start = i
                            break
                    json_str = '\n'.join(lines[json_start:])
                    parsed = json.loads(json_str)

                    results = parsed.get('Results', parsed.get('results', [])) if isinstance(parsed, dict) else []
                    for r in results:
                        target = r.get('Target', '')
                        for vuln in r.get('Vulnerabilities', []):
                            vulnerabilities.append({
                                'target': target,
                                'pkg_name': vuln.get('PkgName', ''),
                                'installed_version': vuln.get('InstalledVersion', ''),
                                'fixed_version': vuln.get('FixedVersion', ''),
                                'severity': vuln.get('Severity', 'UNKNOWN'),
                                'title': vuln.get('Title', ''),
                                'description': vuln.get('Description', ''),
                                'cve_id': vuln.get('CveID', vuln.get('VulnerabilityID', '')),
                                'references': vuln.get('References', []),
                            })
                except Exception as parse_err:
                    logger.warning(f'[Trivy] Error parsing vulnerability JSON: {parse_err}')
        except Exception as e:
            logger.warning(f'[Trivy] Error parsing vulnerability output: {e}')

        scan_results['vulnerabilities'] = vulnerabilities
        scan_results['findings_count'] = len(vulnerabilities)

        logger.info(f'[Trivy] ✓ Found {len(vulnerabilities)} vulnerabilities')

        logger.info('=' * 80)
        logger.info(f'✅ TRIVY SCAN COMPLETE: {scan_id}')
        logger.info(f'   Vulnerabilities: {scan_results.get("findings_count", 0)}')
        logger.info('=' * 80)

        return True, scan_results
    
    except Exception as e:
        logger.exception(f'Exception in run_trivy_scan: {e}')
        return False, {
            'error': str(e),
            'scan_id': scan_id,
            'status': 'failed'
        }


def run_snyk_scan(repo_path, scan_id):
    """
    Run Snyk scan on repository using WSL (SAST + Open Source)
    Runs snyk code test --json (SAST) and snyk test --json (SCA)

    Args:
        repo_path: Path to cloned repository
        scan_id: Unique scan identifier

    Returns:
        Tuple of (success: bool, scan_results: dict)
    """
    try:
        logger.debug('=' * 80)
        logger.debug(f'🔍 SNYK SCAN: {scan_id}')
        logger.debug(f'   Repository: {repo_path}')
        logger.debug('=' * 80)

        wsl_repo_path = get_wsl_path(repo_path)

        # Check if snyk is available (try default PATH + common installation dirs)
        logger.info('[Snyk] Checking for snyk availability...')
        snyk_path = ''
        check_locations = [
            'command -v snyk 2>/dev/null',
            'ls /home/mp/.npm-global/bin/snyk 2>/dev/null',
            'ls /usr/local/bin/snyk 2>/dev/null',
            'ls /usr/bin/snyk 2>/dev/null',
        ]
        for check_cmd in check_locations:
            chk_success, chk_out, _ = run_wsl_command(check_cmd)
            if chk_success and chk_out and chk_out.strip():
                snyk_path = chk_out.strip()
                logger.info(f'[Snyk] ✓ Found at: {snyk_path}')
                break

        if not snyk_path:
            logger.warning('[Snyk] ✗ Snyk not found - skipping')
            return True, {
                'scan_id': scan_id,
                'timestamp': datetime.now().isoformat(),
                'repository': os.path.basename(repo_path),
                'status': 'skipped',
                'message': 'Snyk not installed',
                'results': [],
                'findings_count': 0
            }

        snyk_bin = snyk_path.strip().split('\n')[-1]
        snyk_bin_dir = os.path.dirname(snyk_bin) if os.path.dirname(snyk_bin) else ''
        if snyk_bin_dir:
            snyk_prefix = f'PATH={snyk_bin_dir}:$PATH '
        else:
            snyk_prefix = ''

        # Get SNYK_TOKEN from env or .env
        snyk_token = os.environ.get('SNYK_TOKEN', '')
        if not snyk_token:
            try:
                from modules.env_config import env_config
                snyk_token = env_config.read_env().get('SNYK_TOKEN', '')
            except Exception:
                pass

        if not snyk_token:
            logger.warning('[Snyk] ✗ SNYK_TOKEN not configured - skipping')
            return True, {
                'scan_id': scan_id,
                'timestamp': datetime.now().isoformat(),
                'repository': os.path.basename(repo_path),
                'status': 'skipped',
                'message': 'SNYK_TOKEN not configured',
                'results': [],
                'findings_count': 0
            }

        # Snyk severity mapping: error -> HIGH, warning -> MEDIUM, note -> LOW
        def map_snyk_severity(sev):
            s = str(sev).lower() if sev else 'note'
            if s in ('error', 'high'):
                return 'HIGH'
            elif s in ('warning', 'medium'):
                return 'MEDIUM'
            return 'LOW'

        all_results = []
        findings_count = 0

        # --- Run snyk code test --json (SAST) ---
        logger.info('[Snyk] Starting SAST scan (snyk code test)...')
        snyk_code_cmd = (
            f'cd {shlex.quote(wsl_repo_path)} && '
            f'{snyk_prefix}'
            f'SNYK_TOKEN={shlex.quote(snyk_token)} '
            f'snyk code test --json 2>/dev/null || true'
        )
        code_success, code_stdout, code_stderr = run_wsl_command(snyk_code_cmd, timeout=600)
        sast_raw = code_stdout or ''
        if code_stdout and code_stdout.strip() and code_stdout.strip() != 'true':
            try:
                code_parsed = json.loads(code_stdout)
                runs = code_parsed.get('runs', [])
                for run in runs:
                    for result in run.get('results', []):
                        locations = result.get('locations', [])
                        for loc in locations:
                            phys = loc.get('physicalLocation', {})
                            artifact = phys.get('artifactLocation', {})
                            region = phys.get('region', {})
                            all_results.append({
                                'type': 'sast',
                                'file': artifact.get('uri', ''),
                                'line': region.get('startLine', 0) or 0,
                                'ruleId': result.get('ruleId', ''),
                                'title': result.get('ruleId', '').split('/')[-1].replace('-', ' ').title(),
                                'message': result.get('message', {}).get('text', ''),
                                'severity': map_snyk_severity(result.get('level', 'note')),
                                'category': 'code',
                                'sources': ['snyk']
                            })
            except Exception as e:
                logger.warning(f'[Snyk] Error parsing SAST JSON: {e}')
                logger.warning(f'[Snyk] SAST raw output (first 800 chars): {str(code_stdout)[:800]}')

        # --- Run snyk test --json (SCA / Open Source) ---
        def _run_snyk_sca(extra_flags=''):
            _, out, _ = run_wsl_command(
                f'cd {shlex.quote(wsl_repo_path)} && {snyk_prefix}SNYK_TOKEN={shlex.quote(snyk_token)} snyk test --json {extra_flags}2>/dev/null || true',
                timeout=600
            )
            return out or ''

        def _parse_sca_json(json_str):
            """Parse a single snyk test --json output into findings.
            Handles both dict (snyk test --json) and list (snyk test --json --all-projects)."""
            results = []
            try:
                parsed = json.loads(json_str)
                items = parsed if isinstance(parsed, list) else [parsed]
                for item in items:
                    if item.get('error'):
                        continue
                    vulns = item.get('vulnerabilities', [])
                    if not vulns and 'runs' in item:
                        for run in item.get('runs', []):
                            for result in run.get('results', []):
                                locations = result.get('locations', [])
                                for loc in locations:
                                    phys = loc.get('physicalLocation', {})
                                    artifact = phys.get('artifactLocation', {})
                                    region = phys.get('region', {})
                                    results.append({
                                        'type': 'sca',
                                        'file': artifact.get('uri', ''),
                                        'line': region.get('startLine', 0) or 0,
                                        'ruleId': result.get('ruleId', ''),
                                        'title': result.get('ruleId', '').split('/')[-1].replace('-', ' ').title(),
                                        'message': result.get('message', {}).get('text', ''),
                                        'severity': map_snyk_severity(result.get('level', 'note')),
                                        'category': 'dependencies',
                                        'sources': ['snyk']
                                    })
                    else:
                        for vuln in vulns:
                            results.append({
                                'type': 'sca',
                                'file': vuln.get('packageName', ''),
                                'line': 0,
                                'ruleId': vuln.get('id', ''),
                                'title': vuln.get('title', ''),
                                'message': f"{vuln.get('packageName', '')} {vuln.get('version', '')}: {vuln.get('description', '')}",
                                'severity': map_snyk_severity(vuln.get('severity', 'note')),
                                'category': 'dependencies',
                                'sources': ['snyk'],
                                'details': {
                                    'snyk': {
                                        'package': vuln.get('packageName', ''),
                                        'installed': vuln.get('version', ''),
                                        'fixed': vuln.get('fixedIn', [None])[0] if vuln.get('fixedIn') else '',
                                        'cve': vuln.get('identifiers', {}).get('CVE', [''])[0] if vuln.get('identifiers', {}).get('CVE') else '',
                                    }
                                }
                            })
            except Exception as e:
                logger.warning(f'[Snyk] Error parsing SCA JSON: {e}')
            return results

        logger.info('[Snyk] Starting SCA scan (snyk test)...')

        # Detect manifest files in the repo
        ls_cmd = f'ls -1d {shlex.quote(wsl_repo_path)}/pom.xml {shlex.quote(wsl_repo_path)}/package.json {shlex.quote(wsl_repo_path)}/requirements.txt {shlex.quote(wsl_repo_path)}/yarn.lock {shlex.quote(wsl_repo_path)}/Gemfile 2>/dev/null || true'
        _, ls_out, _ = run_wsl_command(ls_cmd)
        manifests = []
        if ls_out:
            for line in ls_out.strip().splitlines():
                fname = os.path.basename(line.strip())
                if fname == 'package.json':
                    manifests.append(('npm', 'JavaScript/Node.js'))
                elif fname:
                    manifests.append((fname, fname))

        logger.info(f'[Snyk] SCA: Detected manifests: {[m[0] for m in manifests]}')

        sca_raw_parts = []
        scanned = False

        def _snyk_out_has_vulns(out_str):
            """Check if Snyk JSON output contains real findings (not error JSON).
            Handles both dict (snyk test --json) and list (snyk test --json --all-projects)."""
            if not out_str or not out_str.strip() or out_str.strip() == 'true':
                return False
            try:
                parsed = json.loads(out_str.strip())
                if isinstance(parsed, list):
                    if not parsed:
                        return False
                    for item in parsed:
                        if item.get('error'):
                            continue
                        if item.get('vulnerabilities') is not None:
                            return True
                    return False
                if parsed.get('error'):
                    return False
                has_vulns = parsed.get('vulnerabilities') is not None
                has_runs = 'runs' in parsed
                return has_vulns or has_runs
            except json.JSONDecodeError:
                return bool(out_str.strip())

        for manifest_name, label in manifests:
            logger.info(f'[Snyk] SCA: Scanning {label} ({manifest_name})...')
            if manifest_name == 'npm':
                run_wsl_command(f'cd {shlex.quote(wsl_repo_path)} && npm install --production 2>/dev/null || true', timeout=300)
                out = _run_snyk_sca()
            elif manifest_name == 'requirements.txt':
                out = _run_snyk_sca(f'--file=requirements.txt --package-manager=pip ')
                if out and 'ENOTDIR' in out:
                    logger.warning('[Snyk] SCA: pip scan skipped — Snyk pip spawn bug on this WSL (ENOTDIR)')
                    out = ''
            else:
                out = _run_snyk_sca(f'--file={shlex.quote(manifest_name)} ')
            if _snyk_out_has_vulns(out):
                sca_raw_parts.append(out)
                scanned = True
                logger.info(f'[Snyk] SCA: {label} yielded findings')

        if not scanned:
            logger.warning('[Snyk] SCA: No manifest succeeded — trying unqualified scan')
            out = _run_snyk_sca()
            if _snyk_out_has_vulns(out):
                sca_raw_parts.append(out)

        sca_raw = ''
        for part in sca_raw_parts:
            all_results.extend(_parse_sca_json(part))
            sca_raw += part + '\n'

        findings_count = len(all_results)

        scan_results = {
            'scan_id': scan_id,
            'timestamp': datetime.now().isoformat(),
            'repository': os.path.basename(repo_path),
            'raw_output': f'SAST: {len(sast_raw)} chars, SCA: {len(sca_raw)} chars',
            'status': 'completed',
            'results': all_results,
            'findings_count': findings_count,
            '_debug_sast_raw': sast_raw[:2000],
            '_debug_sca_raw': sca_raw[:2000],
        }

        logger.info(f'[Snyk] ✓ Found {findings_count} total issues (SAST + SCA)')
        logger.info('=' * 80)

        return True, scan_results

    except Exception as e:
        logger.exception(f'Exception in run_snyk_scan: {e}')
        return False, {
            'error': str(e),
            'scan_id': scan_id,
            'status': 'failed',
            'results': [],
            'findings_count': 0
        }


def save_scan_results(scan_results, scan_id):
    """
    Save scan results to logs directory (handles both OpenGrep and Trivy results)
    
    Args:
        scan_results: Either a dict with 'opengrep' and 'trivy' keys, or single tool result
        scan_id: Unique scan identifier
    
    Returns:
        Path to output directory or None
    """
    try:
        logger.debug('[Save] Saving scan results...')
        
        logs_dir = get_logs_directory()
        if not logs_dir:
            logger.error('[Save] Failed to get logs directory')
            return None
        
        # Create tool-output directory
        output_dir = os.path.join(logs_dir, 'tool-output', scan_id)
        os.makedirs(output_dir, exist_ok=True)
        logger.debug(f'[Save] Output directory: {output_dir}')
        
        # Determine if we have tools
        has_opengrep = isinstance(scan_results, dict) and 'opengrep' in scan_results
        has_truffle = isinstance(scan_results, dict) and 'truffle' in scan_results
        has_trivy = isinstance(scan_results, dict) and 'trivy' in scan_results
        has_snyk = isinstance(scan_results, dict) and 'snyk' in scan_results
        
        saved_files = []
        
        # Save OpenGrep results if present
        if has_opengrep:
            opengrep_file = os.path.join(output_dir, 'opengrep.json')
            try:
                with open(opengrep_file, 'w', encoding='utf-8') as f:
                    json.dump(scan_results['opengrep'], f, indent=2, default=str)
                
                file_size = os.path.getsize(opengrep_file)
                logger.debug(f'[Save] ✓ OpenGrep results saved: {opengrep_file} ({file_size} bytes)')
                saved_files.append(opengrep_file)
            except Exception as e:
                logger.exception(f'[Save] Error writing OpenGrep results: {e}')
        
        # Save Truffle results if present
        if has_truffle:
            truffle_file = os.path.join(output_dir, 'truffle.json')
            try:
                with open(truffle_file, 'w', encoding='utf-8') as f:
                    json.dump(scan_results['truffle'], f, indent=2, default=str)
                
                file_size = os.path.getsize(truffle_file)
                logger.debug(f'[Save] ✓ Truffle results saved: {truffle_file} ({file_size} bytes)')
                saved_files.append(truffle_file)
            except Exception as e:
                logger.exception(f'[Save] Error writing Truffle results: {e}')
        
        # Save Trivy results if present
        if has_trivy:
            trivy_file = os.path.join(output_dir, 'trivy.json')
            try:
                with open(trivy_file, 'w', encoding='utf-8') as f:
                    json.dump(scan_results['trivy'], f, indent=2, default=str)
                
                file_size = os.path.getsize(trivy_file)
                logger.debug(f'[Save] ✓ Trivy results saved: {trivy_file} ({file_size} bytes)')
                saved_files.append(trivy_file)
            except Exception as e:
                logger.exception(f'[Save] Error writing Trivy results: {e}')
        
        # Save Snyk results if present
        if has_snyk:
            snyk_file = os.path.join(output_dir, 'snyk.json')
            try:
                with open(snyk_file, 'w', encoding='utf-8') as f:
                    json.dump(scan_results['snyk'], f, indent=2, default=str)

                file_size = os.path.getsize(snyk_file)
                logger.debug(f'[Save] ✓ Snyk results saved: {snyk_file} ({file_size} bytes)')
                saved_files.append(snyk_file)
            except Exception as e:
                logger.exception(f'[Save] Error writing Snyk results: {e}')

        # Save Merged results if present
        has_merged = isinstance(scan_results, dict) and 'merged' in scan_results
        if has_merged:
            merged_file = os.path.join(output_dir, 'merged.json')
            try:
                with open(merged_file, 'w', encoding='utf-8') as f:
                    json.dump(scan_results['merged'], f, indent=2, default=str)
                
                file_size = os.path.getsize(merged_file)
                logger.debug(f'[Save] ✓ Merged results saved: {merged_file} ({file_size} bytes)')
                saved_files.append(merged_file)
            except Exception as e:
                logger.exception(f'[Save] Error writing Merged results: {e}')
        
        # Fallback: if scan_results doesn't have opengrep/trivy keys, save as single opengrep.json
        if not (has_opengrep or has_trivy) and isinstance(scan_results, dict):
            results_file = os.path.join(output_dir, 'opengrep.json')
            try:
                with open(results_file, 'w', encoding='utf-8') as f:
                    json.dump(scan_results, f, indent=2, default=str)
                
                file_size = os.path.getsize(results_file)
                logger.debug(f'[Save] ✓ Results saved to: {results_file} ({file_size} bytes)')
                saved_files.append(results_file)
            except Exception as e:
                logger.exception(f'[Save] Error writing results file: {e}')
        
        if saved_files:
            logger.debug(f'[Save] Total files saved: {len(saved_files)}')
            return output_dir
        else:
            logger.error('[Save] No files were saved')
            return None
    
    except Exception as e:
        logger.exception(f'Exception in save_scan_results: {e}')
        return None


def merge_findings(opengrep_results, truffle_results, trivy_results, scan_id, repo_name=None, repo_owner=None, repo_branch=None, is_pr_scan=False, pr_number=None, pr_title=None, pr_head_ref=None, scan_types=None, snyk_results=None):
    """
    Merge findings from all 3 tools (OpenGrep, TruffleHog, Trivy) into unified structure.
    Removes duplicates by file + line + issue type, but keeps all tool sources.
    Excludes findings from .git/ directory (artifacts of scanning process, not repo findings).
    
    Args:
        opengrep_results: OpenGrep scan results
        truffle_results: TruffleHog scan results
        trivy_results: Trivy scan results
        scan_id: Unique scan ID
        repo_name: Repository name
        repo_owner: Repository owner
        repo_branch: Branch scanned
        is_pr_scan: Whether this is a PR scan
        pr_number: PR number (if PR scan)
        pr_title: PR title (if PR scan)
        pr_head_ref: PR head reference (if PR scan)
        scan_types: List of scan types run
    """
    logger.debug('=' * 80)
    logger.debug('🔄 MERGING FINDINGS FROM ALL TOOLS')
    logger.debug('=' * 80)
    
    merged_findings = []
    seen_issues = {}
    finding_id = 1
    
    def should_exclude_finding(path):
        """
        Exclude findings from .git/ directory (artifacts of scan process).
        These are not real repo findings, but rather artifacts from cloning with auth token.
        """
        return path.startswith('.git/') or path.startswith('.git\\') or '/.git/' in path or '\\.git\\' in path
    
    def normalize_severity(sev):
        sev_lower = str(sev).upper() if sev else 'INFO'
        if sev_lower in ['ERROR', 'CRITICAL', 'HIGH']:
            return 'CRITICAL'
        elif sev_lower in ['WARNING', 'MEDIUM']:
            return 'MEDIUM'
        return 'LOW'
    
    def get_issue_type(item, source):
        if source == 'opengrep':
            check_id = item.get('check_id', '')
            if 'private-key' in check_id or 'secret' in check_id:
                return 'private_key'
            elif 'sql' in check_id.lower() or 'injection' in check_id.lower():
                return 'sql_injection'
            elif 'eval' in check_id.lower():
                return 'code_injection'
            return 'code_issue'
        elif source == 'trufflehog':
            detector = item.get('DetectorName', '')
            if 'PrivateKey' in detector:
                return 'private_key'
            elif 'Github' in detector:
                return 'github_token'
            return 'secret'
        elif source == 'trivy':
            return 'vulnerability'
        return 'unknown'
    
    # Process OpenGrep
    for finding in (opengrep_results.get('results', []) or []):
        path = finding.get('path', 'unknown')
        
        # Skip .git/ directory findings (artifacts of scan process)
        if should_exclude_finding(path):
            logger.info(f'[Merge] 🚫 Skipping .git/ artifact: {path}')
            continue
        
        line = finding.get('start', {}).get('line', 0)
        check_id = finding.get('check_id', 'unknown')
        extra = finding.get('extra', {})
        issue_type = get_issue_type(finding, 'opengrep')
        key = f"{path}:{line}:{issue_type}"
        
        if key in seen_issues:
            existing = seen_issues[key]
            if 'opengrep' not in existing['sources']:
                existing['sources'].append('opengrep')
            continue
        
        cwe_list = []
        for c in (extra.get('metadata', {}).get('cwe', [])):
            if isinstance(c, str) and 'CWE-' in c:
                cwe_list.append(c.split(':')[0] if ':' in c else c)
        
        severity = normalize_severity(extra.get('severity', 'WARNING'))
        if issue_type in ['private_key', 'github_token', 'secret']:
            severity = 'CRITICAL'
        merged_findings.append({
            'id': str(finding_id),
            'file': path,
            'line': line,
            'type': issue_type,
            'title': check_id.split('.')[-1].replace('-', ' ').title(),
            'message': extra.get('message', ''),
            'severity': severity,
            'category': 'secrets' if issue_type in ['private_key', 'github_token', 'secret'] else 'code',
            'cwe': cwe_list,
            'sources': ['opengrep'],
            'details': {'opengrep': {'check_id': check_id}}
        })
        seen_issues[key] = merged_findings[-1]
        finding_id += 1
    
    # Process TruffleHog
    for finding in (truffle_results.get('results', []) or []):
        if 'DetectorType' not in finding:
            continue
        metadata = finding.get('SourceMetadata', {}).get('Data', {}).get('Filesystem', {})
        path = metadata.get('file', 'unknown')
        
        # Skip .git/ directory findings (artifacts of scan process)
        if should_exclude_finding(path):
            logger.info(f'[Merge] 🚫 Skipping .git/ artifact: {path}')
            continue
        
        line = metadata.get('line', 0)
        detector_name = finding.get('DetectorName', '')
        issue_type = get_issue_type(finding, 'trufflehog')
        key = f"{path}:{line}:{issue_type}"
        
        if key in seen_issues:
            existing = seen_issues[key]
            if 'trufflehog' not in existing['sources']:
                existing['sources'].append('trufflehog')
            continue
        
        merged_findings.append({
            'id': str(finding_id),
            'file': path,
            'line': line,
            'type': issue_type,
            'title': detector_name,
            'message': finding.get('DetectorDescription', ''),
            'severity': 'CRITICAL' if issue_type == 'private_key' else 'HIGH',
            'category': 'secrets',
            'cwe': ['CWE-798'] if issue_type == 'private_key' else [],
            'sources': ['trufflehog'],
            'details': {'trufflehog': {'detector': detector_name}}
        })
        seen_issues[key] = merged_findings[-1]
        finding_id += 1
    
    # Default snyk_results to empty if not provided
    if snyk_results is None:
        snyk_results = {'results': [], 'findings_count': 0}

    # Process Snyk findings (SAST + SCA)
    for finding in (snyk_results.get('results', []) or []):
        path = finding.get('file', 'unknown')

        if should_exclude_finding(path):
            logger.info(f'[Merge] 🚫 Skipping .git/ artifact: {path}')
            continue

        line = finding.get('line', 0)
        issue_type = finding.get('type', 'code_issue')
        rule_id = finding.get('ruleId', '')
        key = f"{path}:{line}:{issue_type}:snyk:{rule_id}"

        if key in seen_issues:
            existing = seen_issues[key]
            if 'snyk' not in existing['sources']:
                existing['sources'].append('snyk')
            continue

        merged_findings.append({
            'id': str(finding_id),
            'file': path,
            'line': line,
            'type': issue_type,
            'title': finding.get('title', ''),
            'message': finding.get('message', ''),
            'severity': normalize_severity(finding.get('severity', 'MEDIUM')),
            'category': finding.get('category', 'code'),
            'cwe': finding.get('cwe', []),
            'ruleId': rule_id,
            'sources': ['snyk'],
            'details': finding.get('details', {})
        })
        seen_issues[key] = merged_findings[-1]
        finding_id += 1

        # Process Trivy vulnerability findings
    for vuln in (trivy_results.get('vulnerabilities', []) or []):
        path = vuln.get('target', 'unknown')
        pkg = vuln.get('pkg_name', 'unknown')
        cve = vuln.get('cve_id', '')
        issue_type = get_issue_type(vuln, 'trivy')
        key = f"{path}:{pkg}:{cve}"

        if key in seen_issues:
            existing = seen_issues[key]
            if 'trivy' not in existing['sources']:
                existing['sources'].append('trivy')
            continue

        title = vuln.get('title', cve) or cve
        raw_fixed = vuln.get('fixed_version', '')
        if ',' in raw_fixed:
            try:
                from packaging.version import parse as parse_version
                candidates = [v.strip() for v in raw_fixed.split(',') if v.strip()]
                candidates.sort(key=lambda v: parse_version(v))
                latest_fixed = candidates[-1]
            except Exception:
                latest_fixed = raw_fixed
        else:
            latest_fixed = raw_fixed
        merged_findings.append({
            'id': str(finding_id),
            'file': path,
            'line': 0,
            'type': issue_type,
            'title': title,
            'message': f"{pkg} {vuln.get('installed_version', '')} -> {latest_fixed}: {vuln.get('description', '')}",
            'severity': normalize_severity(vuln.get('severity', 'UNKNOWN')),
            'category': 'dependencies',
            'cwe': [],
            'sources': ['trivy'],
            'details': {
                'trivy': {
                    'package': pkg,
                    'installed': vuln.get('installed_version', ''),
                    'fixed': latest_fixed,
                    'cve': cve,
                }
            }
        })
        seen_issues[key] = merged_findings[-1]
        finding_id += 1
    
    # Cross-tool CVE dedup: merge findings from different tools that share the same CVE
    cve_groups = {}
    for idx, f in enumerate(merged_findings):
        cve = ''
        details = f.get('details', {}) or {}
        for tool_details in details.values():
            if isinstance(tool_details, dict):
                cve = tool_details.get('cve', '') or tool_details.get('cve_id', '') or cve
        if cve and cve.startswith('CVE-'):
            if cve not in cve_groups:
                cve_groups[cve] = []
            cve_groups[cve].append(idx)
    keep_indices = set(range(len(merged_findings)))
    for cve, indices in cve_groups.items():
        if len(indices) < 2:
            continue
        primary = indices[0]
        for dup_idx in indices[1:]:
            if dup_idx not in keep_indices:
                continue
            dup = merged_findings[dup_idx]
            primary_f = merged_findings[primary]
            for s in dup.get('sources', []):
                if s not in primary_f.get('sources', []):
                    primary_f['sources'] = primary_f.get('sources', []) + [s]
            if len(dup.get('message', '')) > len(primary_f.get('message', '')):
                primary_f['message'] = dup['message']
            if dup.get('file', '').endswith('.xml') or dup.get('file', '').endswith('.json') or '/' in dup.get('file', '').replace('\\', '/'):
                if not (primary_f.get('file', '').endswith('.xml') or primary_f.get('file', '').endswith('.json') or '/' in primary_f.get('file', '').replace('\\', '/')):
                    primary_f['file'] = dup['file']
            dup_details = dup.get('details', {}) or {}
            for tool_name, tool_detail in dup_details.items():
                if tool_name not in primary_f.get('details', {}):
                    primary_f['details'][tool_name] = tool_detail
            keep_indices.discard(dup_idx)
    merged_findings = [merged_findings[i] for i in sorted(keep_indices)]
    finding_id = len(merged_findings)
    
    # Summary
    severity_counts = {'CRITICAL': 0, 'MEDIUM': 0, 'LOW': 0}
    category_counts = {'secrets': 0, 'code': 0, 'dependencies': 0}
    
    for f in merged_findings:
        severity_counts[f['severity']] = severity_counts.get(f['severity'], 0) + 1
        category_counts[f['category']] = category_counts.get(f['category'], 0) + 1
    
    multi_source = sum(1 for f in merged_findings if len(f['sources']) > 1)
    
    merged_result = {
        'scan_id': scan_id,
        'timestamp': datetime.now().isoformat(),
        'repo_name': repo_name,
        'repo_owner': repo_owner,
        'repo_branch': repo_branch,
        'scan_source': 'pr_webhook' if is_pr_scan else 'manual',
        'is_pr_scan': is_pr_scan,
        'pr_number': pr_number if is_pr_scan else None,
        'pr_title': pr_title if is_pr_scan else None,
        'pr_head_ref': pr_head_ref if is_pr_scan else None,
        'scan_types': scan_types or ['sats', 'sbom', 'secret'],
        'summary': {
            'total_unique': len(merged_findings),
            'multi_source_findings': multi_source,
            'by_severity': severity_counts,
            'by_category': category_counts,
            'tool_breakdown': {
                'opengrep': opengrep_results.get('findings_count', 0),
                'trufflehog': truffle_results.get('findings_count', 0),
                'trivy': trivy_results.get('findings_count', 0),
                'snyk': snyk_results.get('findings_count', 0)
            }
        },
        'findings': merged_findings
    }
    
    logger.info(f'[Merge] ✓ Merged {len(merged_findings)} unique findings')
    logger.info(f'[Merge]   CRITICAL: {severity_counts.get("CRITICAL", 0)}')
    logger.info(f'[Merge]   MEDIUM: {severity_counts.get("MEDIUM", 0)}')
    logger.info(f'[Merge]   LOW: {severity_counts.get("LOW", 0)}')
    logger.info(f'[Merge]   Multi-source: {multi_source}')
    if is_pr_scan:
        logger.info(f'[Merge]   PR Scan: #{pr_number} - {pr_title}')
    # Apply FP suppressions from human-governed false positive management
    try:
        from modules.fp_manager import apply_suppressions_to_findings
        merged_findings = apply_suppressions_to_findings(merged_findings)
    except Exception as e:
        logger.warning(f'[Merge] FP suppression skipped: {e}')

    logger.info('=' * 80)

    return merged_result


def trigger_scan(repo_id, repo_name, repo_owner, repo_url, repo_branch='main', scan_types=None, 
                 is_pr_scan=False, pr_number=None, pr_title=None, pr_head_ref=None):
    """
    Main entry point - Complete scan workflow (clone -> scan -> save -> cleanup)
    
    Args:
        repo_id: Repository ID
        repo_name: Repository name
        repo_owner: Repository owner
        repo_url: Repository URL
        repo_branch: Branch to scan (default: main)
        scan_types: List of scan types to run ['sats', 'sbom', 'secret'], default all
        is_pr_scan: Boolean - True if this is a PR scan
        pr_number: PR number (e.g., 42)
        pr_title: PR title
        pr_head_ref: PR head reference (e.g., 'refs/pull/42/head')
    
    Returns:
        Dict with status and scan details
    """
    if scan_types is None:
        scan_types = ['sats', 'sbom', 'secret']
    
    scan_id = generate_scan_id()
    clone_path = None
    
    # Set default empty results for each scan type
    opengrep_results = {'status': 'skipped', 'findings_count': 0, 'results': []}
    truffle_results = {'status': 'skipped', 'findings_count': 0, 'results': []}
    trivy_results = {'status': 'skipped', 'findings_count': 0, 'results': []}
    snyk_results = {'status': 'skipped', 'findings_count': 0, 'results': []}
    
    try:
        logger.debug('')
        logger.debug('╔' + '═' * 78 + '╗')
        logger.debug('║' + ' COMPLETE SCAN WORKFLOW '.center(78) + '║')
        logger.debug('╚' + '═' * 78 + '╝')
        logger.debug(f'Scan ID: {scan_id}')
        logger.debug(f'Repository: {repo_owner}/{repo_name} (ID: {repo_id})')
        logger.debug(f'Branch: {repo_branch}')
        logger.debug(f'URL: {repo_url}')
        logger.debug(f'Scan Types: {scan_types}')
        
        # ========== STEP 1: CLONE ==========
        logger.debug('')
        logger.debug('╔' + '─' * 78 + '╗')
        logger.debug('║ STEP 1/6: CLONING REPOSITORY'.ljust(79) + '║')
        logger.debug('╚' + '─' * 78 + '╝')
        
        clone_result = clone_repository(repo_id, repo_name, repo_owner, repo_url, repo_branch, scan_id=scan_id)
        
        if clone_result['status'] != 'success':
            logger.error(f'[Step 1] ✗ Clone failed: {clone_result["message"]}')
            return {
                'status': 'error',
                'message': f'Clone failed: {clone_result["message"]}',
                'scan_id': scan_id,
                'repo_id': repo_id,
                'repo_name': repo_name,
                'error_details': clone_result.get('error_details', '')
            }
        
        clone_details = clone_result.get('clone_details', {})
        clone_path = clone_details.get('clone_path', None)
        logger.info(f'[Step 1] ✓ Clone successful: {clone_path}')
        
        # ========== STEP 2: RUN SCANS BASED ON scan_types ==========
        step_num = 2
        
        # SATS = OpenGrep (includes Slither internally)
        if 'sats' in scan_types:
            logger.debug('')
            logger.debug('╔' + '─' * 78 + '╗')
            logger.debug(f'║ STEP {step_num}/6: RUNNING SATS (OPENGREP + SLITHER)'.ljust(79) + '║')
            logger.debug('╚' + '─' * 78 + '╝')
            
            success, opengrep_results = run_opengrep_scan(clone_path, scan_id)
            
            if not success:
                logger.warning(f'[Step {step_num}] ⚠ OpenGrep failed: {opengrep_results.get("error", "Unknown error")}')
                logger.warning(f'[Step {step_num}] Continuing with other scan types...')
                opengrep_results = {
                    'status': 'failed',
                    'error': opengrep_results.get("error", "Unknown error"),
                    'findings_count': 0,
                    'results': []
                }
            
            logger.info(f'[Step {step_num}] ✓ SATS complete: {opengrep_results.get("findings_count", 0)} findings')
            step_num += 1
            time.sleep(5)
        
        # SECRET = TruffleHog
        if 'secret' in scan_types:
            logger.debug('')
            logger.debug('╔' + '─' * 78 + '╗')
            logger.debug(f'║ STEP {step_num}/6: RUNNING SECRET SCAN (TRUFFLEHOG)'.ljust(79) + '║')
            logger.debug('╚' + '─' * 78 + '╝')
            
            success, truffle_results = run_truffle_scan(clone_path, scan_id)
            
            if not success:
                logger.warning(f'[Step {step_num}] ⚠ TruffleHog had issues: {truffle_results.get("error", "Unknown")}')
                truffle_results = {
                    'status': 'failed',
                    'findings_count': 0,
                    'results': []
                }
            
            logger.info(f'[Step {step_num}] ✓ Secret scan complete: {truffle_results.get("findings_count", 0)} secrets')
            step_num += 1
            time.sleep(5)
        
        # SBOM = Trivy
        if 'sbom' in scan_types:
            logger.debug('')
            logger.debug('╔' + '─' * 78 + '╗')
            logger.debug(f'║ STEP {step_num}/6: RUNNING SBOM SCAN (TRIVY)'.ljust(79) + '║')
            logger.debug('╚' + '─' * 78 + '╝')
            
            success_trivy, trivy_results = run_trivy_scan(clone_path, scan_id)
            
            if not success_trivy:
                logger.warning(f'[Step {step_num}] ⚠ Trivy failed: {trivy_results.get("error", "Unknown error")}')
                trivy_results = {
                    'status': 'failed',
                    'error': trivy_results.get("error", "Unknown error"),
                    'findings_count': 0,
                    'results': []
                }
            
            logger.info(f'[Step {step_num}] ✓ SBOM complete: {trivy_results.get("findings_count", 0)} components')
            step_num += 1
            time.sleep(5)
        
        # SNYK = Snyk SAST + SCA
        if 'snyk' in scan_types:
            logger.debug('')
            logger.debug('╔' + '─' * 78 + '╗')
            logger.debug(f'║ STEP {step_num}/6: RUNNING SNYK SCAN (SAST + SCA)'.ljust(79) + '║')
            logger.debug('╚' + '─' * 78 + '╝')
            
            success_snyk, snyk_results = run_snyk_scan(clone_path, scan_id)
            
            if not success_snyk:
                logger.warning(f'[Step {step_num}] ⚠ Snyk failed: {snyk_results.get("error", "Unknown error")}')
                snyk_results = {
                    'status': 'failed',
                    'error': snyk_results.get("error", "Unknown error"),
                    'findings_count': 0,
                    'results': []
                }
            
            logger.info(f'[Step {step_num}] ✓ Snyk complete: {snyk_results.get("findings_count", 0)} findings')
            step_num += 1
        
        # ========== STEP 5: MERGE FINDINGS ==========
        logger.debug('')
        logger.debug('╔' + '─' * 78 + '╗')
        logger.debug(f'║ STEP {step_num}/6: MERGING FINDINGS'.ljust(79) + '║')
        logger.debug('╚' + '─' * 78 + '╝')
        
        merged_results = merge_findings(
            opengrep_results, truffle_results, trivy_results, scan_id, 
            repo_name=repo_name, 
            repo_owner=repo_owner, 
            repo_branch=repo_branch,
            is_pr_scan=is_pr_scan,
            pr_number=pr_number,
            pr_title=pr_title,
            pr_head_ref=pr_head_ref,
            scan_types=scan_types,
            snyk_results=snyk_results
        )
        logger.info(f'[Step {step_num}] ✓ Merged: {merged_results["summary"]["total_unique"]} unique findings')
        
        # ========== STEP 6: SAVE RESULTS ==========
        logger.debug('')
        logger.debug('╔' + '─' * 78 + '╗')
        logger.debug(f'║ STEP {step_num}/6: SAVING RESULTS'.ljust(79) + '║')
        logger.debug('╚' + '─' * 78 + '╝')
        
        combined_results = {
            'opengrep': opengrep_results,
            'truffle': truffle_results,
            'trivy': trivy_results,
            'snyk': snyk_results,
            'merged': merged_results,
            'repo_name': repo_name,
            'repo_owner': repo_owner,
            'repo_branch': repo_branch,
            'scan_types': scan_types
        }
        
        results_dir = save_scan_results(combined_results, scan_id)
        
        if not results_dir:
            logger.error(f'[Step {step_num}] ✗ Failed to save results')
            # Continue to cleanup
            cleanup_cloned_repo(repo_owner, repo_name, scan_id=scan_id)
            
            return {
                'status': 'error',
                'message': 'Failed to save scan results',
                'scan_id': scan_id,
                'repo_id': repo_id,
                'repo_name': repo_name
            }
        
        logger.info(f'[Step {step_num}] ✓ Results saved: {results_dir}')
        
        # ========== STEP 6: CLEANUP ==========
        logger.debug('')
        logger.debug('╔' + '─' * 78 + '╗')
        logger.debug('║ STEP 6/6: CLEANUP'.ljust(79) + '║')
        logger.debug('╚' + '─' * 78 + '╝')
        
        cleanup_success = cleanup_cloned_repo(repo_owner, repo_name, scan_id=scan_id)
        
        if cleanup_success:
            logger.info('[Step 6] ✓ Repository cleanup successful')
        else:
            logger.warning('[Step 6] ⚠ Repository cleanup had issues (may retry manually)')
        
        # ========== FINAL RESULT ==========
        logger.info('')
        logger.info('╔' + '═' * 78 + '╗')
        logger.info('║' + ' SCAN COMPLETE ✅ '.center(78) + '║')
        logger.info('╚' + '═' * 78 + '╝')
        logger.info(f'Scan ID: {scan_id}')
        logger.info(f'Repository: {repo_owner}/{repo_name}')
        
        merged_summary = merged_results.get('summary', {})
        logger.info(f'--- MERGED FINDINGS ---')
        logger.info(f'Total Unique: {merged_summary.get("total_unique", 0)}')
        logger.info(f'  CRITICAL: {merged_summary.get("by_severity", {}).get("CRITICAL", 0)}')
        logger.info(f'  MEDIUM: {merged_summary.get("by_severity", {}).get("MEDIUM", 0)}')
        logger.info(f'  LOW: {merged_summary.get("by_severity", {}).get("LOW", 0)}')
        logger.info(f'Multi-source: {merged_summary.get("multi_source_findings", 0)}')
        logger.info(f'--- TOOL BREAKDOWN ---')
        logger.info(f'OpenGrep: {opengrep_results.get("findings_count", 0)}')
        logger.info(f'Trivy: {trivy_results.get("findings_count", 0)}')
        logger.info(f'Snyk: {snyk_results.get("findings_count", 0)}')
        logger.info(f'Results: {results_dir}')
        logger.info('')
        
        # ========== INCLUDE FINDINGS FOR PR SCANS ==========
        findings = merged_results.get('findings', [])

        return {
            'status': 'success',
            'message': f'Successfully completed scan for {repo_owner}/{repo_name}',
            'scan_id': scan_id,
            'repo_id': repo_id,
            'repo_name': repo_name,
            'repo_owner': repo_owner,
            'clone_path': clone_path,
            'results_dir': results_dir,
            'opengrep_findings': opengrep_results.get('findings_count', 0),
            'trivy_findings': trivy_results.get('findings_count', 0),
            'total_findings': opengrep_results.get('findings_count', 0) + trivy_results.get('findings_count', 0),
            'findings': findings,
            'tool_breakdown': {
                'opengrep': opengrep_results.get('findings_count', 0),
                'truffle': truffle_results.get('findings_count', 0),
                'trivy': trivy_results.get('findings_count', 0),
                'snyk': snyk_results.get('findings_count', 0)
            },
            'cleanup_success': cleanup_success,
            # PR Scan metadata
            'is_pr_scan': is_pr_scan,
            'pr_number': pr_number,
            'pr_title': pr_title,
            'pr_head_ref': pr_head_ref
        }
    
    except Exception as e:
        logger.exception(f'Exception in trigger_scan: {e}')
        
        # Attempt cleanup on error
        if clone_path:
            try:
                logger.info('[Error] Attempting cleanup after exception...')
                cleanup_cloned_repo(repo_owner, repo_name, scan_id=scan_id)
            except Exception as cleanup_error:
                logger.warning(f'[Error] Cleanup also failed: {cleanup_error}')
        
        return {
            'status': 'error',
            'message': f'Scan workflow failed: {str(e)}',
            'scan_id': scan_id,
            'repo_id': repo_id,
            'repo_name': repo_name,
            'error_details': str(e)
        }
