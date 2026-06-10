"""
Repositories Tab Module - Repository management and scanning
Integrates with GitHub API to fetch installed app repositories
"""

import os
import jwt
import time
import requests
import json
import logging
import ssl
from urllib3.poolmanager import PoolManager
from requests.adapters import HTTPAdapter
from modules.env_config import env_config
from modules.settings import get_github_credentials_for_user
from models.database import User
from flask import current_app

logger = logging.getLogger(__name__)


class _SSLFallbackAdapter(HTTPAdapter):
    """Adapter that retries with verify=False if SSL handshake fails."""
    def send(self, request, **kwargs):
        try:
            return super().send(request, **kwargs)
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            logger.warning(f'SSL handshake failed, retrying with verify=False: {e}')
            kwargs['verify'] = False
            return super().send(request, **kwargs)


def github_session():
    """Create a requests Session with retries and SSL fallback for cross-platform compat."""
    sess = requests.Session()
    sess.headers.update({
        'User-Agent': 'VIRTUAL_PLUMBER',
        'Accept': 'application/vnd.github.v3+json',
    })
    retry = requests.adapters.Retry(
        total=2,
        backoff_factor=0.5,
        allowed_methods=['GET', 'POST'],
        status_forcelist=[500, 502, 503, 504],
    )
    adapter = _SSLFallbackAdapter(max_retries=retry)
    sess.mount('https://', adapter)
    sess.mount('http://', adapter)
    return sess


def get_github_credentials():
    """
    Get GitHub credentials - tries database (encrypted) first, falls back to .env
    
    Returns:
        tuple: (app_id, secret_key)
    """
    try:
        app = current_app._get_current_object()
    except RuntimeError:
        from app import create_app
        app = create_app()
    
    def _do_get():
        try:
            admin_user = User.query.filter(
                User.encrypted_github_app_id.isnot(None),
                User.encrypted_github_key.isnot(None)
            ).first()
            
            if admin_user:
                creds = get_github_credentials_for_user(admin_user.id)
                if creds and creds.get('github_app_id'):
                    app_id = creds['github_app_id']
                    secret_key = decrypt_github_key(admin_user.id)
                    if app_id and secret_key:
                        logger.debug('Using encrypted credentials from database')
                        return app_id, secret_key
        except Exception as e:
            logger.warning(f'Database credentials not available: {e}')
        
        app_id = env_config.get_setting('GITHUB_APP_ID')
        secret_key = env_config.get_setting('GITHUB_SECRET_KEY')
        return app_id, secret_key
    
    with app.app_context():
        return _do_get()


def decrypt_github_key(user_id):
    """Decrypt GitHub private key for a user"""
    from utils.crypto_utils import decrypt_credential
    user = User.query.get(user_id)
    if user and user.encrypted_github_key:
        return decrypt_credential(user.encrypted_github_key)
    return None


def validate_private_key(secret_key):
    """
    Validate that the private key is in proper RSA format
    """
    if not secret_key:
        return False, "Private key is empty"
    
    # Check if it starts with RSA header
    if not secret_key.startswith('-----BEGIN'):
        return False, "Private key doesn't start with '-----BEGIN' marker"
    
    # Check if it ends with RSA footer
    if not secret_key.strip().endswith('-----END RSA PRIVATE KEY-----') and not secret_key.strip().endswith('-----END PRIVATE KEY-----'):
        return False, "Private key doesn't end with proper '-----END' marker"
    
    # Check if it has newlines (multiline format)
    if '\n' not in secret_key:
        return False, "Private key doesn't have newlines (malformed)"
    
    return True, "Private key format is valid"


def get_github_app_token():
    """
    Generate a JWT token for GitHub App authentication
    Uses encrypted database credentials first, falls back to .env
    
    Returns:
        JWT token for GitHub App API calls
    """
    try:
        logger.debug("Starting get_github_app_token...")
        app_id, secret_key = get_github_credentials()
        
        logger.debug(f"App ID: {app_id}")
        logger.debug(f"Secret Key present: {bool(secret_key)}")
        logger.debug(f"Secret Key length: {len(secret_key) if secret_key else 0}")
        
        if not app_id or not secret_key:
            logger.error("Missing credentials - app_id or secret_key is empty")
            return None
        
        # Validate the private key format
        is_valid, validation_msg = validate_private_key(secret_key)
        if not is_valid:
            logger.error(f"Private key validation failed: {validation_msg}")
            logger.error(f"Key starts with: {secret_key[:50]}...")
            logger.error(f"Key ends with: ...{secret_key[-50:]}")
            return None
        
        logger.info("Private key validation passed")
        
        payload = {
            'iat': int(time.time()),
            'exp': int(time.time()) + 300,
            'iss': app_id
        }
        
        logger.debug(f"JWT Payload: {payload}")
        
        try:
            token = jwt.encode(payload, secret_key, algorithm='RS256')
            logger.debug(f"✓ Generated JWT token successfully (length: {len(token)})")
            return token
        except Exception as e:
            logger.error(f"JWT encoding failed: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            return None
    except Exception as e:
        logger.exception(f"Exception in get_github_app_token: {e}")
        return None


def get_installations():
    """
    Fetch all installations of the GitHub App
    
    Returns:
        List of installation IDs
    """
    try:
        logger.debug("Attempting to get GitHub App installations...")
        token = get_github_app_token()
        if not token:
            logger.error("Failed to generate GitHub App token")
            return []
        
        logger.debug(f"Generated token (first 20 chars): {str(token)[:20]}...")
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'VIRTUAL_PLUMBER'
        }
        
        response = github_session().get(
            'https://api.github.com/app/installations',
            headers=headers,
            timeout=10
        )
        
        logger.debug(f"Installations API response: {response.status_code}")
        logger.debug(f"Response headers: {dict(response.headers)}")
        logger.debug(f"Response body: {response.text[:500]}")
        
        if response.status_code == 200:
            installations = response.json()
            ids = [inst.get('id') for inst in installations]
            logger.debug(f"Found installations: {ids}")
            return ids
        else:
            logger.error(f"Failed to fetch installations: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return []
    
    except Exception as e:
        logger.exception(f"Exception in get_installations: {e}")
        return []


def get_installation_token(installation_id):
    """
    Get an access token for a specific installation
    
    Args:
        installation_id: GitHub App installation ID
    
    Returns:
        Access token for the installation
    """
    try:
        logger.debug(f"Getting token for installation {installation_id}...")
        token = get_github_app_token()
        if not token:
            logger.error("Failed to get JWT token")
            return None
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'VIRTUAL_PLUMBER'
        }
        
        url = f'https://api.github.com/app/installations/{installation_id}/access_tokens'
        logger.debug(f"POST to {url}")
        
        response = github_session().post(
            url,
            headers=headers,
            timeout=10
        )
        
        logger.debug(f"Installation token response status: {response.status_code}")
        logger.debug(f"Installation token response: {response.text[:500]}")
        
        if response.status_code == 201:
            data = response.json()
            token = data.get('token')
            if token:
                logger.debug(f"Got installation token (first 20 chars): {token[:20]}...")
            else:
                logger.error("No token in response")
            return token
        else:
            logger.error(f"Error getting installation token: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return None
    
    except Exception as e:
        logger.exception(f"Exception in get_installation_token: {e}")
        return None


def get_repositories():
    """
    Fetch all repositories where GitHub App is installed
    
    Returns:
        List of repositories with details
    """
    try:
        logger.debug("Starting get_repositories...")
        installations = get_installations()
        logger.debug(f"Found {len(installations)} installations: {installations}")
        repositories = []
        
        for installation_id in installations:
            logger.debug(f"Processing installation: {installation_id}")
            token = get_installation_token(installation_id)
            if not token:
                logger.error(f"Failed to get token for installation {installation_id}")
                continue
            
            logger.debug(f"Got token for installation {installation_id}")
            headers = {
                'Authorization': f'token {token}',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            response = github_session().get(
                'https://api.github.com/installation/repositories',
                headers=headers,
                timeout=10
            )
            
            logger.debug(f"Repository fetch response: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                repos = data.get('repositories', [])
                logger.debug(f"Found {len(repos)} repositories")
                
                for repo in repos:
                    repositories.append({
                        'name': repo.get('name', 'N/A'),
                        'id': repo.get('id'),
                        'branch': repo.get('default_branch', 'main'),
                        'url': repo.get('html_url', ''),
                        'owner': repo.get('owner', {}).get('login', 'N/A')
                    })
            else:
                logger.error(f"Error fetching installation repositories: {response.text}")
        
        logger.debug(f"Returning {len(repositories)} total repositories")
        try:
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cache_path = os.path.join(root_dir, '.repos_cache.json')
            with open(cache_path, 'w', encoding='utf-8') as cf:
                json.dump(repositories, cf)
        except Exception as e:
            logger.warning(f"Could not write repos cache: {e}")
        return repositories
    
    except Exception as e:
        logger.exception(f"Error fetching repositories: {e}")
        try:
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cache_path = os.path.join(root_dir, '.repos_cache.json')
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as cf:
                    cached = json.load(cf)
                    logger.debug(f"Returning {len(cached)} repositories from cache")
                    return cached
        except Exception as e2:
            logger.warning(f"Could not read repos cache: {e2}")

        return []


def get_repository_by_id(repo_id):
    """Get specific repository details"""
    repos = get_repositories()
    for repo in repos:
        if repo['id'] == repo_id:
            return repo
    return None


def get_repository_branches(owner, repo_name):
    """
    Fetch all branches for a specific repository
    """
    try:
        installations = get_installations()
        
        for installation_id in installations:
            token = get_installation_token(installation_id)
            if not token:
                logger.warning(f"Failed to get token for installation {installation_id}")
                continue
            
            headers = {
                'Authorization': f'token {token}',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            url = f'https://api.github.com/repos/{owner}/{repo_name}/branches'
            response = github_session().get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                branches = response.json()
                branch_names = [branch['name'] for branch in branches]
                logger.debug(f"Found {len(branch_names)} branches for {owner}/{repo_name}: {branch_names}")
                return branch_names
            elif response.status_code == 404:
                logger.warning(f"Repository {owner}/{repo_name} not found in this installation")
                continue
            else:
                logger.warning(f"Error fetching branches for {owner}/{repo_name}: {response.status_code}")
                continue
        
        logger.warning(f"Could not fetch branches for {owner}/{repo_name}")
        return []
    
    except Exception as e:
        logger.exception(f"Error fetching branches for {owner}/{repo_name}: {e}")
        return []


def get_repository_stats():
    """Get aggregate statistics for all repositories based on scan history"""
    repos = get_repositories()
    
    if not repos:
        return {
            'total': 0,
            'passed': 0,
            'failed': 0,
            'warning': 0,
            'avg_coverage': 0,
            'total_issues': 0
        }
    
    from modules.history import get_scan_history
    
    try:
        history = get_scan_history()
        
        repo_scan_map = {}
        for scan in history:
            repo_name = scan.get('repository', '')
            if repo_name not in repo_scan_map:
                repo_scan_map[repo_name] = scan
        
        total = len(repos)
        passed = 0
        failed = 0
        warning = 0
        total_issues = 0
        
        for repo in repos:
            repo_name = repo.get('name', '')
            repo_owner = repo.get('owner', '')
            full_repo_name = f"{repo_owner}/{repo_name}" if repo_owner else repo_name
            
            if full_repo_name in repo_scan_map:
                scan = repo_scan_map[full_repo_name]
                severity = scan.get('severity', {})
                
                critical = severity.get('CRITICAL', 0)
                high = severity.get('HIGH', 0)
                total_findings = scan.get('total_findings', 0)
                
                total_issues += total_findings
                
                if critical > 0:
                    failed += 1
                elif high > 0:
                    warning += 1
                else:
                    passed += 1
            else:
                passed += 1
        
        return {
            'total': total,
            'passed': passed,
            'failed': failed,
            'warning': warning,
            'avg_coverage': 0,
            'total_issues': total_issues
        }
    except Exception as e:
        print(f"Error calculating repository stats: {e}")
        return {
            'total': len(repos),
            'passed': 0,
            'failed': 0,
            'warning': 0,
            'avg_coverage': 0,
            'total_issues': 0
        }
