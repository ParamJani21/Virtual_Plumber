"""
PR Scan Handler Module
Handles automated PR scanning with status updates and GitHub integration
"""

import threading
import logging
import json
import requests
from datetime import datetime

logger = logging.getLogger(__name__)


def trigger_pr_scan(repo_id, repo_name, repo_owner, repo_url, pr_number, pr_title, 
                    pr_head_sha, scan_types=None, user_id=None, repo_branch=None,
                    pr_block_enabled=None, pr_block_severity=None):
    """
    Trigger a PR scan in the background
    """
    try:
        from flask import current_app
        from models.database import db, ScanHistory, User
        
        if scan_types is None:
            scan_types = ['sats', 'sbom', 'secret']
        
        if repo_branch is None:
            repo_branch = 'main'
        
        scan_id = f"pr-{pr_number}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        
        if user_id is None:
            admin_user = User.query.filter_by(role='admin').first()
            user_id = admin_user.id if admin_user else 1
        
        scan_history = ScanHistory(
            user_id=user_id,
            scan_id=scan_id,
            repo_id=str(repo_id),
            repo_name=repo_name,
            repo_owner=repo_owner,
            repo_branch=repo_branch,
            is_pr_scan=True,
            pr_number=pr_number,
            pr_title=pr_title,
            pr_head_ref=f'refs/pull/{pr_number}/head',
            scan_types=json.dumps(scan_types),
            scan_status='pending',
            started_at=datetime.utcnow()
        )
        
        db.session.add(scan_history)
        db.session.commit()
        
        logger.debug(f'Created ScanHistory record for PR #{pr_number}: {scan_id}')
        
        scan_thread = threading.Thread(
            target=_run_pr_scan_background,
            args=(scan_id, repo_id, repo_name, repo_owner, repo_url, pr_number, 
                    pr_title, pr_head_sha, scan_types, user_id, repo_branch,
                    pr_block_enabled, pr_block_severity),
            daemon=True
        )
        scan_thread.start()
        
        return {
            'status': 'success',
            'scan_id': scan_id,
            'pr_number': pr_number,
            'message': f'PR scan triggered for PR #{pr_number}'
        }
    
    except Exception as e:
        logger.exception(f'Error triggering PR scan: {e}')
        return {
            'status': 'error',
            'message': f'Failed to trigger PR scan: {str(e)}'
        }


def _run_pr_scan_background(scan_id, repo_id, repo_name, repo_owner, repo_url, 
                            pr_number, pr_title, pr_head_sha, scan_types, user_id, repo_branch='main',
                            pr_block_enabled=None, pr_block_severity=None):
    """
    Background worker function for PR scanning
    """
    from app import create_app
    from modules.github_status import set_github_status_check
    from modules.control_apis import trigger_scan, cleanup_cloned_repo
    from modules.pr_comment import post_pr_comment, generate_scan_summary_comment
    from models.database import db, ScanHistory
    
    start_time = datetime.utcnow()
    app = create_app()
    
    def update_status(state, description):
        try:
            set_github_status_check(
                repo_owner=repo_owner,
                repo_name=repo_name,
                sha=pr_head_sha,
                state=state,
                context='virtual_plumber/scan',
                description=description
            )
        except Exception:
            pass
    
    try:
        with app.app_context():
            scan_history = ScanHistory.query.filter_by(scan_id=scan_id).first()
            if scan_history:
                scan_history.scan_status = 'in_progress'
                db.session.commit()
        
        update_status('pending', 'Scanning for security vulnerabilities...')
        
        with app.app_context():
            scan_result = trigger_scan(
                repo_id=str(repo_id),
                repo_name=repo_name,
                repo_owner=repo_owner,
                repo_url=repo_url,
                repo_branch=repo_branch,
                scan_types=scan_types,
                is_pr_scan=True,
                pr_number=pr_number,
                pr_title=pr_title,
                pr_head_ref=f'refs/pull/{pr_number}/head'
            )
        
        with app.app_context():
            scan_history = ScanHistory.query.filter_by(scan_id=scan_id).first()
            if scan_history:
                duration = (datetime.utcnow() - start_time).total_seconds()
                scan_history.duration_seconds = int(duration)
                scan_history.completed_at = datetime.utcnow()
                
                if scan_result and scan_result.get('status') == 'success':
                    scan_history.scan_status = 'completed'
                    logger.debug(f'Scan {scan_id} completed with status success')
                    
                    findings = scan_result.get('findings', [])
                    logger.debug(f'Scan result has {len(findings)} findings')
                    
                    if findings:
                        summary = {
                            'total_unique': len(findings),
                            'by_severity': {},
                            'by_category': {},
                            'tool_breakdown': scan_result.get('tool_breakdown', {})
                        }
                        
                        for finding in findings:
                            severity = finding.get('severity', 'unknown')
                            category = finding.get('category', 'unknown')
                            summary['by_severity'][severity] = summary['by_severity'].get(severity, 0) + 1
                            summary['by_category'][category] = summary['by_category'].get(category, 0) + 1
                        
                        scan_history.summary = json.dumps(summary)
                    
                    files = scan_result.get('files', {})
                    if files:
                        scan_history.findings_file_path = files.get('merged')
                        scan_history.opengrep_file_path = files.get('opengrep')
                        scan_history.truffle_file_path = files.get('truffle')
                        scan_history.trivy_file_path = files.get('trivy')
                    
                    db.session.commit()
                    logger.debug(f'Scan {scan_id} DB updated successfully')
                    
                    summary_data = json.loads(scan_history.summary) if scan_history.summary else {}
                    total_findings = summary_data.get('total_unique', 0)
                    critical_count = summary_data.get('by_severity', {}).get('CRITICAL', 0)
                    high_count = summary_data.get('by_severity', {}).get('HIGH', 0)
                    medium_count = summary_data.get('by_severity', {}).get('MEDIUM', 0)
                    low_count = summary_data.get('by_severity', {}).get('LOW', 0)
                    
                    # Check block settings (use passed params, fallback to DB)
                    if pr_block_enabled is None or pr_block_severity is None:
                        from models.database import User
                        admin_user = User.query.filter_by(role='admin').first()
                        block_enabled = admin_user.pr_block_enabled if admin_user else False
                        block_severity = (admin_user.pr_block_severity or 'HIGH') if admin_user else 'HIGH'
                    else:
                        block_enabled = pr_block_enabled
                        block_severity = pr_block_severity
                    
                    severity_rank = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
                    block_threshold = severity_rank.get(block_severity.upper(), 1)
                    meets_threshold = False
                    for sev, rank in severity_rank.items():
                        if rank <= block_threshold and summary_data.get('by_severity', {}).get(sev, 0) > 0:
                            meets_threshold = True
                            break
                    
                    if meets_threshold and block_enabled:
                        update_status('failure', f'Blocking PR - {critical_count}C {high_count}H {medium_count}M {low_count}L')
                        # Close the PR
                        try:
                            from modules.repos import get_installations, get_installation_token
                            installations = get_installations()
                            if installations:
                                inst_token = get_installation_token(installations[0])
                                if inst_token:
                                    close_url = f'https://api.github.com/repos/{repo_owner}/{repo_name}/pulls/{pr_number}'
                                    close_headers = {
                                        'Authorization': f'token {inst_token}',
                                        'Accept': 'application/vnd.github.v3+json',
                                        'User-Agent': 'VIRTUAL_PLUMBER/1.0'
                                    }
                                    close_payload = {'state': 'closed'}
                                    close_resp = requests.patch(close_url, json=close_payload, headers=close_headers, timeout=10)
                                    if close_resp.status_code == 200:
                                        logger.info(f'PR #{pr_number} closed due to blocking findings')
                                    else:
                                        logger.warning(f'Failed to close PR #{pr_number}: {close_resp.status_code} {close_resp.text}')
                        except Exception as close_e:
                            logger.error(f'Error closing PR #{pr_number}: {close_e}')
                    elif critical_count > 0:
                        update_status('neutral', f'{critical_count} critical, {high_count} high issues')
                    elif high_count > 0:
                        update_status('neutral', f'Found {total_findings} issues')
                    else:
                        update_status('success', f'Found {total_findings} issues')
                    
                    logger.debug(f'About to post PR comment with {len(findings)} findings')
                    comment_body = generate_scan_summary_comment(findings, scan_id)
                    logger.debug(f'Generated comment body length: {len(comment_body)} chars')
                    
                    comment_result = post_pr_comment(repo_owner, repo_name, pr_number, comment_body)
                    logger.info(f'PR comment post result: {comment_result}')
                
                else:
                    scan_history.scan_status = 'failed'
                    db.session.commit()
                    logger.info(f'Scan {scan_id} failed: {scan_result.get("message") if scan_result else "Unknown error"}')
                    update_status('error', 'Scan failed')
            
            clone_path = scan_result.get('clone_path') if scan_result else None
            if clone_path:
                logger.debug(f'[PR Scan] Cleaning up cloned repo: {repo_owner}/{repo_name}')
                cleanup_cloned_repo(repo_owner, repo_name, scan_id=scan_id)
            
            logger.debug(f'[PR Scan] Scan {scan_id} fully completed')

    except Exception as e:
        logger.exception(f'Error in background PR scan: {e}')
        
        with app.app_context():
            scan_history = ScanHistory.query.filter_by(scan_id=scan_id).first()
            if scan_history:
                scan_history.scan_status = 'failed'
                duration = (datetime.utcnow() - start_time).total_seconds()
                scan_history.duration_seconds = int(duration)
                scan_history.completed_at = datetime.utcnow()
                db.session.commit()
            
            update_status('error', f'Scan error: {str(e)[:50]}')
        
        logger.debug(f'[PR Scan] Cleaning up cloned repo after exception: {repo_owner}/{repo_name}')
        cleanup_cloned_repo(repo_owner, repo_name, scan_id=scan_id)
