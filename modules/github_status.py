"""
GitHub Status Check Integration
Updates PR status checks with scan results
"""

import requests
import logging
from app import create_app

logger = logging.getLogger(__name__)


def set_github_status_check(repo_owner, repo_name, sha, state, context, 
                            description, target_url=None):
    """
    Set a GitHub status check on a commit
    """
    app = create_app()
    
    def _do_set():
        from modules.repos import get_installations, get_installation_token
        
        valid_states = ['pending', 'success', 'failure', 'error', 'neutral']
        if state not in valid_states:
            logger.warning(f'Invalid GitHub status state: {state}')
            return False
        
        installations = get_installations()
        if not installations:
            logger.warning('No GitHub App installations found')
            return False
        
        inst_token = get_installation_token(installations[0])
        if not inst_token:
            logger.warning('No installation token available')
            return False
        
        payload = {
            'state': state,
            'context': context,
            'description': description[:100] if len(description) > 100 else description
        }
        
        if target_url:
            payload['target_url'] = target_url
        
        url = f'https://api.github.com/repos/{repo_owner}/{repo_name}/statuses/{sha}'
        
        headers = {
            'Authorization': f'token {inst_token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'VIRTUAL_PLUMBER/1.0'
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 201:
            logger.info(f'GitHub status check set: {repo_owner}/{repo_name}@{sha[:7]} -> {state}')
            return True
        else:
            logger.warning(f'Failed to set GitHub status: {response.status_code} {response.text}')
            return False
    
    with app.app_context():
        return _do_set()


def create_github_check_run(repo_owner, repo_name, head_sha, name='VIRTUAL_PLUMBER Scan', 
                            status='queued', conclusion=None, details_url=None):
    """
    Create a GitHub Check Run (more detailed than status checks)
    """
    app = create_app()
    
    def _do_create():
        from modules.repos import get_installations, get_installation_token
        
        installations = get_installations()
        if not installations:
            logger.warning('No GitHub App installations found')
            return None
        
        inst_token = get_installation_token(installations[0])
        if not inst_token:
            logger.warning('No installation token available')
            return None
        
        payload = {
            'name': name,
            'head_sha': head_sha,
            'status': status
        }
        
        if conclusion:
            payload['conclusion'] = conclusion
        
        if details_url:
            payload['details_url'] = details_url
        
        url = f'https://api.github.com/repos/{repo_owner}/{repo_name}/check-runs'
        
        headers = {
            'Authorization': f'token {inst_token}',
            'Accept': 'application/vnd.github.checks-preview+json',
            'User-Agent': 'VIRTUAL_PLUMBER/1.0'
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 201:
            check_run = response.json()
            logger.info(f'GitHub check run created: {repo_owner}/{repo_name}@{head_sha[:7]} -> {name}')
            return check_run
        else:
            logger.warning(f'Failed to create GitHub check run: {response.status_code} {response.text}')
            return None
    
    with app.app_context():
        return _do_create()


def update_github_check_run(repo_owner, repo_name, check_run_id, status='in_progress', 
                            conclusion=None, details_url=None, output=None):
    """
    Update an existing GitHub Check Run
    """
    app = create_app()
    
    def _do_update():
        from modules.repos import get_installations, get_installation_token
        
        installations = get_installations()
        if not installations:
            return False
        
        inst_token = get_installation_token(installations[0])
        if not inst_token:
            return False
        
        payload = {'status': status}
        
        if conclusion:
            payload['conclusion'] = conclusion
        
        if details_url:
            payload['details_url'] = details_url
        
        if output:
            payload['output'] = output
        
        url = f'https://api.github.com/repos/{repo_owner}/{repo_name}/check-runs/{check_run_id}'
        
        headers = {
            'Authorization': f'token {inst_token}',
            'Accept': 'application/vnd.github.checks-preview+json',
            'User-Agent': 'VIRTUAL_PLUMBER/1.0'
        }
        
        response = requests.patch(url, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 200:
            logger.info(f'GitHub check run updated: {repo_owner}/{repo_name}#{check_run_id} -> {status}')
            return True
        else:
            logger.warning(f'Failed to update GitHub check run: {response.status_code} {response.text}')
            return False
    
    with app.app_context():
        return _do_update()
