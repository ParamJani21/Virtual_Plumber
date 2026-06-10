"""
GitHub PR Comment Integration
Posts brief scan results to PR as comments
"""

import requests
import logging

logger = logging.getLogger(__name__)


def post_pr_comment(repo_owner, repo_name, pr_number, body):
    """
    Post a comment to a PR
    """
    from app import create_app
    from modules.repos import get_installations, get_installation_token
    
    app = create_app()
    
    try:
        with app.app_context():
            installations = get_installations()
            if not installations:
                logger.error('No GitHub App installations found')
                return False
            
            inst_token = get_installation_token(installations[0])
            if not inst_token:
                logger.error('No installation token available')
                return False
            
            logger.info(f'Posting PR comment to {repo_owner}/{repo_name}#{pr_number}')
            
            url = f'https://api.github.com/repos/{repo_owner}/{repo_name}/issues/{pr_number}/comments'
            
            headers = {
                'Authorization': f'token {inst_token}',
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'VIRTUAL_PLUMBER/1.0'
            }
            
            payload = {'body': body}
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            
            if response.status_code == 201:
                logger.info(f'PR comment posted successfully to {repo_owner}/{repo_name}#{pr_number}')
                return True
            else:
                logger.error(f'Failed to post PR comment: {response.status_code} - {response.text}')
                return False
    except Exception as e:
        logger.exception(f'Exception posting PR comment: {e}')
        return False


def generate_scan_summary_comment(findings, scan_id=None):
    """
    Generate a brief markdown comment with scan results
    """
    if not findings:
        return "## 🔍 Security Scan Complete\n\n✅ No security issues found!"
    
    severity_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
    counts = {s: 0 for s in severity_order}
    for f in findings:
        sev = f.get('severity', 'LOW').upper()
        if sev in counts:
            counts[sev] += 1
    
    lines = [
        "## 🔍 VIRTUAL_PLUMBER Security Scan Results",
        "",
        "### Summary",
        f"| Severity | Count |",
        f"|:---------|------:|"
    ]
    
    for sev in severity_order:
        if counts[sev] > 0:
            lines.append(f"| **{sev}** | {counts[sev]} |")
    
    lines.append("")
    lines.append("---")
    if scan_id:
        lines.append(f"*Scan ID: `{scan_id}`*")
    lines.append("*Powered by VIRTUAL_PLUMBER*")
    
    return '\n'.join(lines)
