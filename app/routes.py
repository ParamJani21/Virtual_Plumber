from flask import Blueprint, render_template, jsonify, request, current_app, session, redirect, url_for
from markupsafe import escape
import sys
import os
import hmac
import hashlib
import json

# Add parent directory to path for module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.database import db
from modules.overview import get_overview_data
from modules.repos import get_repositories, get_repository_stats, get_repository_branches
from modules.history import get_scan_history, get_history_stats, get_scan_details
from modules.settings import (get_settings, get_integration_status, 
                             get_github_credentials, save_github_credentials, 
                             get_github_credentials_for_user)
from modules.scan_controller import trigger_scan
from auth.decorators import require_login, require_admin, require_role
from auth.utils import get_current_user, log_audit_event

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    """Main route - redirect to login if not authenticated, otherwise show dashboard"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login_page'))
    return redirect(url_for('main.dashboard'))


@bp.route('/dashboard')
@require_login
def dashboard():
    """Render main dashboard page"""
    overview_data = get_overview_data()
    repos_stats = get_repository_stats()
    history_stats = get_history_stats()
    
    context = {
        'overview': overview_data,
        'repos_stats': repos_stats,
        'history_stats': history_stats
    }
    return render_template('dashboard.html', **context)


# API endpoints for tab data
@bp.route('/api/overview')
@require_login
def api_overview():
    """API endpoint for overview data"""
    return jsonify(get_overview_data())


@bp.route('/api/repos')
@require_login
def api_repos():
    """API endpoint for repositories"""
    return jsonify({
        'repositories': get_repositories(),
        'stats': get_repository_stats()
    })


@bp.route('/api/branches/<path:owner>/<path:repo_name>')
@require_login
def api_branches(owner, repo_name):
    """API endpoint to fetch available branches for a repository"""
    try:
        branches = get_repository_branches(owner, repo_name)
        return jsonify({
            'branches': branches,
            'status': 'success'
        })
    except Exception as e:
        current_app.logger.error(f"Error fetching branches for {owner}/{repo_name}: {e}")
        return jsonify({
            'branches': [],
            'status': 'error',
            'message': str(e)
        }), 500


@bp.route('/api/history')
@require_login
def api_history():
    """API endpoint for scan history"""
    history = get_scan_history()
    return jsonify({
        'history': history,
        'stats': get_history_stats(history)
    })


@bp.route('/api/history/<scan_id>')
@require_login
def api_scan_details(scan_id):
    """API endpoint for getting detailed scan information"""
    import re
    if not re.match(r'^[a-zA-Z0-9\-_]+$', scan_id):
        return jsonify({'error': 'Invalid scan_id format'}), 400
    details = get_scan_details(scan_id)
    # Apply FP suppressions to findings
    if details and 'files' in details and 'merged' in details['files']:
        merged_data = details['files'].get('merged', {})
        if merged_data and 'findings' in merged_data:
            try:
                from modules.fp_manager import apply_suppressions_to_findings
                merged_data['findings'] = apply_suppressions_to_findings(merged_data['findings'])
            except Exception:
                pass
    if details:
        # If files exist but are incomplete, return 202 (Accepted) to indicate retry
        if details.get('errors') and not details.get('files'):
            return jsonify({
                'status': 'processing',
                'message': 'Scan results still being written. Please retry in a moment.',
                'errors': details.get('errors', [])
            }), 202
        # Return partial data if some files are incomplete
        if details.get('errors') and details.get('files'):
            response = jsonify(details)
            response.status_code = 206  # 206 Partial Content
            return response
        return jsonify(details), 200
    return jsonify({'error': 'Scan not found', 'status': 'not_found'}), 404


@bp.route('/api/activity')
@require_login
@require_admin
def api_activity():
    """API endpoint for activity log (admin only)"""
    from auth.utils import get_audit_logs
    days = request.args.get('days', 30, type=int)
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    user_id = request.args.get('user_id', None, type=int)
    action = request.args.get('action', None)
    since = request.args.get('since', None)
    since_id = request.args.get('since_id', None, type=int)
    
    result = get_audit_logs(
        user_id=user_id,
        action=action,
        days=days,
        limit=limit,
        offset=offset,
        since=since,
        since_id=since_id
    )
    
    return jsonify(result), 200


@bp.route('/api/activity/users')
@require_login
@require_admin
def api_activity_users():
    """API endpoint to get users with audit log counts"""
    try:
        from auth.utils import get_audit_log_users
        days = request.args.get('days', 30, type=int)
        result = get_audit_log_users(days=days)
        return jsonify(result), 200
    except Exception as e:
        current_app.logger.error(f"Error in api_activity_users: {e}")
        return jsonify({'error': str(e), 'users': [], 'total': 0}), 500


@bp.route('/user-activity/<int:user_id>')
@require_login
@require_admin
def user_activity_page(user_id):
    """Full-screen page showing activity logs for a specific user"""
    from auth.utils import get_audit_logs
    from models.database import User
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return render_template('user_activity.html', target_user=user)


@bp.route('/scan-detail/<scan_id>')
@require_login
def scan_detail_page(scan_id):
    """Full-screen page showing scan details for a specific scan"""
    from models.database import ScanHistory
    scan = ScanHistory.query.filter_by(scan_id=scan_id).first()
    return render_template('scan_detail.html', scan_id=scan_id, scan=scan)


@bp.route('/api/history/filter')
@require_login
def api_history_filter():
    """API endpoint for filtering scan history findings by severity, tool, category, and search"""
    severity = request.args.get('severity', '')
    tool = request.args.get('tool', '')
    category = request.args.get('category', '')
    search = request.args.get('search', '')
    
    # Parse comma-separated values into lists
    severity_list = [s.strip().upper() for s in severity.split(',') if s.strip()]
    tool_list = [t.strip().lower() for t in tool.split(',') if t.strip()]
    category_list = [c.strip().lower() for c in category.split(',') if c.strip()]
    
    # If no filters, return all history
    if not severity_list and not tool_list and not category_list and not search:
        history = get_scan_history()
        return jsonify({'history': history})
    
    # Get history and filter
    history = get_scan_history()
    filtered = []
    
    for scan in history:
        # Filter findings in each scan
        findings = scan.get('findings', [])
        if not findings:
            findings = []
        
        filtered_findings = [
            f for f in findings
            if (not severity_list or f.get('severity', '').upper() in severity_list)
            and (not tool_list or any(
                t == s.lower() or (t == 'truffle' and s.lower() == 'trufflehog')
                for s in f.get('sources', [])
                for t in tool_list
            ))
            and (not category_list or f.get('category', '').lower() in category_list)
            and (not search or search.lower() in (f.get('file', '') or '').lower() or search.lower() in (f.get('message', '') or '').lower() or search.lower() in (f.get('title', '') or '').lower())
        ]
        
        if filtered_findings:  # Only return scans with matching findings
            scan_copy = scan.copy()
            scan_copy['findings'] = filtered_findings
            filtered.append(scan_copy)
    
    return jsonify({'history': filtered})


@bp.route('/api/history/delete', methods=['POST'])
@require_login
def api_delete_history():
    """API endpoint for deleting scans"""
    import os
    import shutil
    import re
    
    data = request.get_json()
    scan_ids = data.get('scan_ids', [])
    
    if not scan_ids:
        return jsonify({'success': False, 'message': 'No scan IDs provided'}), 400
    
    for sid in scan_ids:
        if not re.match(r'^[a-zA-Z0-9\-_]+$', str(sid)):
            return jsonify({'success': False, 'message': f'Invalid scan_id format: {sid}'}), 400
    
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'tool-output')
    deleted_count = 0
    errors = []
    
    for scan_id in scan_ids:
        scan_path = os.path.join(logs_dir, scan_id)
        if os.path.exists(scan_path) and os.path.isdir(scan_path):
            try:
                shutil.rmtree(scan_path)
                deleted_count += 1
            except Exception as e:
                errors.append(f"Failed to delete {scan_id}: {str(e)}")
    
    if deleted_count > 0:
        log_audit_event(
            action='SCAN_HISTORY_DELETED',
            resource_type='scan',
            resource_id=f'{deleted_count} scan(s)',
            new_value={'deleted_ids': scan_ids, 'count': deleted_count}
        )
        return jsonify({
            'success': True, 
            'deleted': deleted_count,
            'message': f'Deleted {deleted_count} scan(s)'
        })
    else:
        return jsonify({
            'success': False, 
            'message': 'No scans were deleted. ' + '; '.join(errors) if errors else 'Scans not found'
        }), 400


@bp.route('/api/repos/scan', methods=['POST'])
@require_login
def api_trigger_repo_scan():
    """API endpoint for manual scan triggers."""
    try:
        payload = request.get_json(silent=True) or {}
        repo_id = payload.get('repo_id')
        repo_name = payload.get('repo_name')
        repo_owner = payload.get('repo_owner')
        repo_url = payload.get('repo_url')
        repo_branch = payload.get('repo_branch', 'main')
        scan_types = payload.get('scan_types', ['sats', 'sbom', 'secret'])

        if not repo_id:
            return jsonify({'status': 'error', 'message': 'repo_id is required'}), 400
        
        if not repo_name or not repo_owner:
            return jsonify({'status': 'error', 'message': 'repo_name and repo_owner are required'}), 400
        
        if not repo_url:
            repo_url = f'https://github.com/{repo_owner}/{repo_name}.git'

        current_app.logger.debug('Manual scan requested for repo_id=%s (%s/%s) from %s | scan_types=%s', 
                               repo_id, repo_owner, repo_name, request.remote_addr, scan_types)
        
        # Log immediately before triggering scan so admin sees it right away
        log_audit_event(
            action='SCAN_TRIGGERED',
            resource_type='repository',
            resource_id=repo_id,
            new_value={'repo_name': repo_name, 'repo_owner': repo_owner, 'repo_branch': repo_branch, 'scan_types': scan_types}
        )
        
        # Trigger the actual scan using the controller
        result = trigger_scan(repo_id, repo_name, repo_owner, repo_url, repo_branch, scan_types)
        
        current_app.logger.debug('[RESULT] Status: %s | Message: %s | Keys: %s', 
                               result.get('status'), result.get('message'), list(result.keys()))
        
        if result['status'] == 'success':
            current_app.logger.debug('✓ Scan successful: %s', result['message'])
            return jsonify(result), 200
        else:
            current_app.logger.error('✗ Scan failed: %s', result['message'])
            return jsonify(result), 500
    except Exception as e:
        current_app.logger.exception('Error handling manual scan request: %s', e)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/api/repos/scan-all', methods=['POST'])
@require_login
def api_scan_all_repos():
    """API endpoint to scan all repositories from GitHub App."""
    try:
        from modules.repos import get_repositories
        
        payload = request.get_json(silent=True) or {}
        scan_types = payload.get('scan_types', ['sats', 'sbom', 'secret'])
        
        current_app.logger.debug('Scan all repos requested from %s | scan_types=%s', request.remote_addr, scan_types)
        
        # Check if repos with branch info are provided in the request
        repos_from_request = payload.get('repos', None)
        
        if repos_from_request:
            # Use repos and branches from frontend
            repos_to_scan = repos_from_request
            current_app.logger.debug('Using %d repos with branch info from request', len(repos_to_scan))
        else:
            # Get all repositories from GitHub App (fallback)
            all_repos = get_repositories()
            
            if not all_repos or len(all_repos) == 0:
                return jsonify({'status': 'error', 'message': 'No repositories found'}), 404
            
            # Convert to the format expected by scan
            repos_to_scan = [
                {
                    'repo_id': repo.get('id', ''),
                    'repo_name': repo.get('name', ''),
                    'repo_owner': repo.get('owner', ''),
                    'repo_url': repo.get('url', f'https://github.com/{repo.get("owner", "")}/{repo.get("name", "")}.git'),
                    'repo_branch': repo.get('branch', 'main')
                }
                for repo in all_repos
            ]
        
        triggered_scans = []
        failed_scans = []
        
        total = len(repos_to_scan)
        for idx, repo_info in enumerate(repos_to_scan):
            try:
                repo_id = repo_info.get('repo_id', '')
                repo_name = repo_info.get('repo_name', '')
                repo_owner = repo_info.get('repo_owner', '')
                repo_url = repo_info.get('repo_url', f'https://github.com/{repo_owner}/{repo_name}.git')
                repo_branch = repo_info.get('repo_branch', 'main')
                
                if not repo_id or not repo_name or not repo_owner:
                    failed_scans.append({'repo': f"{repo_owner}/{repo_name}", 'error': 'Missing required fields'})
                    continue
                
                # Trigger scan for this repo with its selected branch
                result = trigger_scan(repo_id, repo_name, repo_owner, repo_url, repo_branch, scan_types)
                
                triggered_scans.append({
                    'repo_id': repo_id,
                    'repo_name': repo_name,
                    'repo_owner': repo_owner,
                    'repo_branch': repo_branch,
                    'status': result.get('status', 'unknown'),
                    'scan_id': result.get('scan_id', '')
                })
                
                current_app.logger.debug('✓ Triggered scan for %s/%s (branch: %s)', repo_owner, repo_name, repo_branch)
                
                # 10-second cooldown between repos (skip after last)
                if idx < total - 1:
                    from modules.overview import BULK_COOLDOWN
                    import time
                    BULK_COOLDOWN.update({
                        'active': True,
                        'current_repo': f'{repo_owner}/{repo_name}',
                        'repo_index': idx + 1,
                        'total_repos': total,
                        'remaining': 10,
                        'updated_at': time.time()
                    })
                    time.sleep(10)
                    BULK_COOLDOWN['active'] = False
                    
            except Exception as scan_err:
                current_app.logger.error('Failed to scan %s: %s', repo_info.get('repo_name', 'unknown'), str(scan_err))
                failed_scans.append({'repo': f"{repo_info.get('repo_owner', 'unknown')}/{repo_info.get('repo_name', 'unknown')}", 'error': str(scan_err)})
        
        log_audit_event(
            action='SCAN_ALL_TRIGGERED',
            resource_type='repository',
            new_value={
                'total_repos': len(repos_to_scan),
                'triggered': len(triggered_scans),
                'scan_types': scan_types
            }
        )
        
        return jsonify({
            'status': 'success',
            'message': f'Triggered {len(triggered_scans)} scans',
            'total_repos': len(repos_to_scan),
            'triggered': triggered_scans,
            'failed': failed_scans
        })
        
    except Exception as e:
        current_app.logger.exception('Error scanning all repos: %s', e)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/api/runtime')
@require_login
def api_runtime():
    """Return runtime information to help diagnose environment (python executable, cwd, PATH)."""
    try:
        import sys
        import os
        info = {
            'python_executable': sys.executable,
            'cwd': os.getcwd(),
            'path': os.environ.get('PATH', '')[:2000]
        }
        current_app.logger.info('Runtime info requested: %s', info)
        return jsonify({'status': 'success', 'runtime': info})
    except Exception as exc:
        current_app.logger.exception('Error collecting runtime info: %s', exc)
        return jsonify({'status': 'error', 'message': str(exc)}), 500


@bp.route('/api/settings')
@require_login
def api_settings():
    """API endpoint for settings"""
    return jsonify({
        'settings': get_settings(),
        'integrations': get_integration_status()
    })


@bp.route('/api/settings/github', methods=['GET'])
@require_login
def api_get_github_credentials():
    """API endpoint to retrieve GitHub credentials (decrypted for authenticated user)"""
    try:
        user = get_current_user()
        if not user:
            return jsonify({
                'status': 'error',
                'message': 'User not authenticated'
            }), 401
        
        # Try database first (encrypted credentials)
        credentials = get_github_credentials_for_user(user.id)
        
        # Fallback to .env if not in database
        if not credentials or not credentials.get('github_app_id'):
            credentials = get_github_credentials()
        
        return jsonify({
            'status': 'success',
            'credentials': credentials
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@bp.route('/api/settings/github', methods=['POST'])
@require_login
def api_save_github_credentials():
    """API endpoint to save GitHub credentials (encrypted in database)"""
    try:
        user = get_current_user()
        if not user:
            return jsonify({
                'status': 'error',
                'message': 'User not authenticated'
            }), 401
        
        data = request.get_json()
        
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'No data provided'
            }), 400
        
        result = save_github_credentials(
            github_app_id=data.get('github_app_id', ''),
            github_app_name=data.get('github_app_name', ''),
            github_secret_key=data.get('github_secret_key', ''),
            ngrok_oauth_token=data.get('ngrok_oauth_token', ''),
            github_webhook_secret=data.get('github_webhook_secret', ''),
            user_id=user.id  # Pass current user ID for encryption
        )
        
        log_audit_event(
            action='GITHUB_CREDENTIALS_UPDATED',
            resource_type='settings',
            status='success' if result.get('status') == 'success' else 'failure'
        )
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error saving credentials: {str(e)}'
        }), 500


@bp.route('/api/settings/pr-scan', methods=['GET'])
@require_login
def api_get_pr_scan_settings():
    """API endpoint to get PR scan toggle setting"""
    try:
        user = get_current_user()
        if not user:
            return jsonify({
                'status': 'error',
                'message': 'User not authenticated'
            }), 401
        
        return jsonify({
            'status': 'success',
            'pr_scan_enabled': user.pr_scan_enabled,
            'pr_block_enabled': user.pr_block_enabled,
            'pr_block_severity': user.pr_block_severity or 'HIGH'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@bp.route('/api/settings/pr-scan', methods=['POST'])
@require_login
def api_update_pr_scan_settings():
    """API endpoint to update PR scan toggle setting"""
    try:
        user = get_current_user()
        if not user:
            return jsonify({
                'status': 'error',
                'message': 'User not authenticated'
            }), 401
        
        data = request.get_json()
        pr_scan_enabled = data.get('pr_scan_enabled', True)
        pr_block_enabled = data.get('pr_block_enabled', False)
        pr_block_severity = data.get('pr_block_severity', 'HIGH')
        
        old_settings = {'pr_scan_enabled': user.pr_scan_enabled, 'pr_block_enabled': user.pr_block_enabled, 'pr_block_severity': user.pr_block_severity or 'HIGH'}
        
        user.pr_scan_enabled = pr_scan_enabled
        user.pr_block_enabled = pr_block_enabled
        user.pr_block_severity = pr_block_severity
        db.session.commit()
        current_app.logger.debug(f'PR scan settings updated: enabled={pr_scan_enabled}, block={pr_block_enabled}, threshold={pr_block_severity} by user {user.id}')
        log_audit_event(
            action='PR_SCAN_SETTINGS_UPDATED',
            resource_type='settings',
            old_value=old_settings,
            new_value={'pr_scan_enabled': pr_scan_enabled, 'pr_block_enabled': pr_block_enabled, 'pr_block_severity': pr_block_severity}
        )
        
        return jsonify({
            'status': 'success',
            'message': f'PR scan settings saved',
            'pr_scan_enabled': user.pr_scan_enabled,
            'pr_block_enabled': user.pr_block_enabled,
            'pr_block_severity': user.pr_block_severity or 'HIGH'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@bp.route('/api/settings/ngrok', methods=['GET'])
@require_login
def api_get_ngrok_settings():
    """API endpoint to get ngrok subdomain setting"""
    try:
        from modules.env_config import env_config
        env_vars = env_config.read_env()
        return jsonify({
            'status': 'success',
            'ngrok_subdomain': env_vars.get('NGROK_SUBDOMAIN', '')
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@bp.route('/api/settings/ngrok', methods=['POST'])
@require_login
def api_update_ngrok_settings():
    """API endpoint to update ngrok subdomain setting"""
    try:
        from modules.env_config import env_config
        
        data = request.get_json()
        ngrok_subdomain = data.get('ngrok_subdomain', '').strip()
        
        env_config.save_setting('NGROK_SUBDOMAIN', ngrok_subdomain)
        
        log_audit_event(
            action='NGROK_SETTINGS_UPDATED',
            resource_type='settings',
            new_value={'ngrok_subdomain': ngrok_subdomain}
        )
        
        current_app.logger.debug(f'Ngrok subdomain updated: {ngrok_subdomain}')
        
        return jsonify({
            'status': 'success',
            'message': 'Ngrok subdomain saved',
            'ngrok_subdomain': ngrok_subdomain
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@bp.route('/api/log', methods=['POST'])
@require_login
def api_client_log():
    """Accept client-side logs (UI events) and write them to server logs."""
    try:
        payload = request.get_json(silent=True) or {}
        event = payload.get('event') or 'client_event'
        details = payload.get('details') or {}
        level = payload.get('level', 'info').lower()

        # Normalize details size
        import json as _json
        try:
            details_str = _json.dumps(details) if not isinstance(details, str) else details
        except Exception:
            details_str = str(details)

        msg = f"ClientLog - {event} - {details_str} - remote={request.remote_addr}"

        if level == 'debug':
            current_app.logger.debug(msg)
        elif level == 'warning' or level == 'warn':
            current_app.logger.warning(msg)
        elif level == 'error':
            current_app.logger.error(msg)
        else:
            current_app.logger.info(msg)

        return jsonify({'status': 'ok'})
    except Exception as e:
        current_app.logger.exception('Error handling client log: %s', e)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/api/export-report')
@require_login
def api_export_report():
    """Generate and download security scan report"""
    import json
    import re
    from datetime import datetime, timezone
    from flask import make_response
    
    def _fmt_report_msg(msg):
        """Format scanner message into structured sections for the report"""
        if not msg:
            return ''
        sections = re.findall(r'##\s+(.+?)\n([\s\S]*?)(?=\n##\s+|$)', msg)
        if not sections:
            return escape(msg)
        html = ''
        for heading, body in sections:
            h = escape(heading.strip())
            b = escape(body.strip())
            html += '<div style="margin:0.5rem 0;padding:0.5rem;background:rgba(15,23,42,0.4);border-left:2px solid #334155;border-radius:0 4px 4px 0;">'
            html += f'<strong style="display:block;color:#e2e8f0;font-size:0.8rem;font-weight:600;margin-bottom:0.25rem;text-transform:uppercase;letter-spacing:0.03em;">{h}</strong>'
            html += f'<div style="color:#94a3b8;font-size:0.75rem;line-height:1.5;white-space:pre-wrap;">{b}</div>'
            html += '</div>'
        return html
    
    try:
        # Get filter params (000 to 111 - date, severity, tool)
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')
        severity_filter = request.args.get('severity', '').split(',') if request.args.get('severity') else []
        tool_filter = request.args.get('tool', '').split(',') if request.args.get('tool') else []
        
        # Get logs directory
        module_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(module_dir)
        logs_dir = os.path.join(project_root, 'logs', 'tool-output')

        from modules.fp_manager import apply_suppressions_to_findings
        
        if not os.path.exists(logs_dir):
            return jsonify({'error': 'No scan data found'}), 404
        
        # Read scans based on filters
        scans = []
        for scan_dir in os.listdir(logs_dir):
            scan_path = os.path.join(logs_dir, scan_dir)
            if not os.path.isdir(scan_path):
                continue
            
            # If tool filter, filter merged.json by sources; else use all merged findings
            if tool_filter:
                merged_file = os.path.join(scan_path, 'merged.json')
                if os.path.exists(merged_file):
                    try:
                        with open(merged_file, 'r') as f:
                            m = json.load(f)
                            m['findings'] = apply_suppressions_to_findings(m.get('findings', []))
                            scan_data = {'scan_id': scan_dir, 'findings': [], 'summary': {'total_unique': 0, 'by_severity': {}}}
                            scan_data['repo_name'] = m.get('repo_name', '')
                            scan_data['repo_owner'] = m.get('repo_owner', '')
                            scan_data['repo_branch'] = m.get('repo_branch', 'main')
                            scan_data['timestamp'] = m.get('timestamp', scan_dir)
                            # Filter findings by tool/source
                            for f in m.get('findings', []):
                                sources = f.get('sources', [])
                                # Check if any of the tool_filter is in sources
                                # Normalize: truffle -> trufflehog, etc.
                                for t in tool_filter:
                                    if t == 'truffle' and 'trufflehog' in sources:
                                        scan_data['findings'].append(f)
                                        break
                                    elif t in sources:
                                        scan_data['findings'].append(f)
                                        break
                            by_sev = {}
                            for f in scan_data['findings']:
                                sev = f.get('severity', 'LOW').upper()
                                by_sev[sev] = by_sev.get(sev, 0) + 1
                            scan_data['summary']['by_severity'] = by_sev
                            scan_data['summary']['total_unique'] = len(scan_data['findings'])
                            if scan_data['findings']:
                                scans.append(scan_data)
                    except Exception:
                        continue
            else:
                merged_file = os.path.join(scan_path, 'merged.json')
                if os.path.exists(merged_file):
                    try:
                        with open(merged_file, 'r') as f:
                            scan_data = json.load(f)
                            scan_data['findings'] = apply_suppressions_to_findings(scan_data.get('findings', []))
                            scan_data['scan_id'] = scan_dir
                            scans.append(scan_data)
                    except Exception:
                        continue
        
        # Apply date filter (bit 0)
        if date_from or date_to:
            filtered_scans = []
            for scan in scans:
                ts = scan.get('timestamp', '')
                if not ts:
                    continue
                # Parse timestamp - could be ISO format or directory name
                try:
                    if 'T' in ts:
                        scan_date = ts.split('T')[0]
                    else:
                        scan_date = ts[:10] if len(ts) >= 10 else ''
                except:
                    scan_date = ''
                
                if date_from and scan_date < date_from:
                    continue
                if date_to and scan_date > date_to:
                    continue
                filtered_scans.append(scan)
            scans = filtered_scans
        
        # Apply severity filter
        if severity_filter:
            for scan in scans:
                scan['findings'] = [f for f in scan.get('findings', []) if f.get('severity', 'LOW').upper() in severity_filter]
                by_sev = {}
                for f in scan['findings']:
                    sev = f.get('severity', 'LOW').upper()
                    by_sev[sev] = by_sev.get(sev, 0) + 1
                scan['summary']['by_severity'] = by_sev
                scan['summary']['total_unique'] = len(scan['findings'])
        
        # Remove scans with no findings after filtering
        scans = [s for s in scans if s.get('summary', {}).get('total_unique', 0) > 0]
        
        # Sort scans: findings first, then clean scans
        scans_with_findings = [s for s in scans if s.get('summary', {}).get('total_unique', 0) > 0]
        scans_clean = [s for s in scans if s.get('summary', {}).get('total_unique', 0) == 0]
        
        # Sort by timestamp descending
        scans_with_findings.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        scans_clean.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        sorted_scans = scans_with_findings + scans_clean
        
        # Calculate totals
        total_repos = len(scans)
        total_findings = sum(s.get('summary', {}).get('total_unique', 0) for s in scans)
        
        severity_totals = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
        for scan in scans:
            by_severity = scan.get('summary', {}).get('by_severity', {})
            for sev in severity_totals:
                severity_totals[sev] += by_severity.get(sev, 0)
        
        # Generate scan sections HTML
        scan_sections_html = ''
        severity_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
        
        for scan in sorted_scans:
            findings = scan.get('findings', [])
            total = scan.get('summary', {}).get('total_unique', 0)
            timestamp = scan.get('timestamp', scan.get('scan_id', ''))
            repo_name = scan.get('repo_name', 'Unknown')
            repo_owner = scan.get('repo_owner', 'Unknown')
            repo_branch = scan.get('repo_branch', 'main')
            
            # Format timestamp
            if 'T' in str(timestamp):
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    formatted_time = str(timestamp)
            else:
                formatted_time = str(timestamp)
            
            repo_name = scan.get('repo_name')
            repo_owner = scan.get('repo_owner')
            repo_branch = scan.get('repo_branch', 'main')
            
            if repo_name and repo_owner:
                repo_full = f"{repo_owner}/{repo_name}"
                branch_display = repo_branch
            else:
                repo_full = scan.get('scan_id', 'Unknown Repository')
                branch_display = 'N/A'
            
            pr_badge = ' <span style="background:linear-gradient(135deg, #667eea, #764ba2);color:white;font-size:0.7rem;padding:2px 6px;border-radius:4px;font-weight:bold;">PR</span>' if scan.get('is_pr_scan') else ''
            
            scan_sections_html += f'''
            <div class="scan-section">
                <div class="scan-header">
                    <div class="scan-header-left">
                        <h3>📁 Scan: {scan.get('scan_id', 'N/A')}</h3>
                        <div class="scan-repo-info">
                            <span>📦 <strong>{repo_full}{pr_badge}</strong></span>
                            <span>🌿 {branch_display}</span>
                        </div>
                    </div>
                    <div class="scan-meta">
                        <span>⏰ <span class="scan-timestamp" data-utc="{timestamp}">{formatted_time}</span></span>
                        <span>📊 {total} Findings</span>
                    </div>
                </div>
'''
            
            if total == 0:
                scan_sections_html += '''
                <div class="no-findings">
                    <div class="icon">✅</div>
                    <p>No security issues found in this scan</p>
                </div>
'''
            else:
                # Group findings by package (Trivy) or file (other tools)
                severity_rank = {sev: i for i, sev in enumerate(severity_order)}
                
                groups = {}
                for finding in findings:
                    trivy_detail = finding.get('details', {}).get('trivy', {})
                    if trivy_detail and trivy_detail.get('package'):
                        group_key = f"trivy:{trivy_detail['package']}"
                    else:
                        group_key = f"file:{finding.get('file', 'unknown')}"
                    if group_key not in groups:
                        groups[group_key] = {'findings': [], 'type': 'trivy' if trivy_detail else 'file'}
                    groups[group_key]['findings'].append(finding)
                
                # Sort groups by worst severity (descending), then by count (descending)
                def group_worst_severity(g):
                    sevs = [f.get('severity', 'LOW').upper() for f in g['findings']]
                    return min(severity_rank.get(s, 99) for s in sevs)
                
                sorted_groups = sorted(groups.values(), key=lambda g: (group_worst_severity(g), -len(g['findings'])))
                
                scan_sections_html += '''
                <table class="findings-table">
                    <thead>
                        <tr>
                            <th style="width: 10%;">Severity</th>
                            <th style="width: 25%;">File / Location</th>
                            <th style="width: 25%;">Finding</th>
                            <th style="width: 40%;">Description</th>
                        </tr>
                    </thead>
                    <tbody>
'''
                for group in sorted_groups:
                    group_findings = sorted(group['findings'], key=lambda x: severity_rank.get(x.get('severity', 'LOW').upper(), 99))
                    first = group_findings[0]
                    
                    # Build group header info
                    if group['type'] == 'trivy':
                        t = first.get('details', {}).get('trivy', {})
                        group_title = t.get('package', 'Unknown')
                        group_file = first.get('file', 'unknown')
                        installed = t.get('installed', '')
                        # Find the highest fixed version across all findings in the group
                        all_fixed = []
                        for gf in group_findings:
                            ft = gf.get('details', {}).get('trivy', {})
                            fv = ft.get('fixed', '')
                            if fv:
                                all_fixed.append(fv)
                        max_fixed = ''
                        if all_fixed:
                            try:
                                from packaging.version import parse as parse_version
                                max_fixed = max(all_fixed, key=lambda v: parse_version(v))
                            except Exception:
                                max_fixed = max(all_fixed)
                        group_version = f'<div class="finding-version"><span style="color:#f87171;font-weight:600;">{installed}</span> → <span style="color:#4ade80;font-weight:600;">{max_fixed}</span></div>' if installed and max_fixed else ''
                    else:
                        group_title = first.get('file', 'Unknown')
                        group_file = group_title
                        group_version = ''
                    
                    worst_sev = group_findings[0].get('severity', 'LOW').upper()
                    worst_sev_class = worst_sev.lower()
                    count = len(group_findings)
                    
                    group_id = f'g{hash(group_title) & 0x7fffffff}'
                    scan_sections_html += f'''
                        <tr class="finding-group-header" onclick="toggleGroup(this)" data-group="{group_id}">
                            <td colspan="4">
                                <div class="group-title-row">
                                    <span class="group-toggle-icon">▶</span>
                                    <span class="severity-badge {worst_sev_class}" style="margin-right:6px;">{worst_sev}</span>
                                    <span class="group-name">{group_title}</span>
                                    <span class="group-count">{count} finding{"s" if count > 1 else ""}</span>
                                    {group_version}
                                </div>
                            </td>
                        </tr>'''
                    
                    for finding in group_findings:
                        sev = finding.get('severity', 'LOW').upper()
                        severity_class = sev.lower()
                        file_path = finding.get('file', 'unknown')
                        line = finding.get('line', 0)
                        title = finding.get('title', 'Unknown')
                        ftype = finding.get('category', 'secrets')
                        message = _fmt_report_msg(finding.get('message', ''))
                        is_suppressed = finding.get('suppressed', False)
                        
                        location = f'{file_path}:{line}' if line > 0 else file_path
                        ft = finding.get('details', {}).get('trivy', {})
                        if ft:
                            pkg = ft.get('package', '')
                            installed = ft.get('installed', '')
                            fixed = ft.get('fixed', '')
                            if pkg:
                                location += f'<div class="finding-type">{pkg}</div>'
                            if installed and fixed:
                                location += f'<div class="finding-version"><span style="color:#f87171;font-weight:600;">{installed}</span> → <span style="color:#4ade80;font-weight:600;">{fixed}</span></div>'
                            elif installed:
                                location += f'<div class="finding-version"><span style="color:#f87171;font-weight:600;">{installed}</span></div>'
                        
                        supp_badge = ''
                        row_style = ''
                        if is_suppressed:
                            supp_badge = '<span class="fp-approved-badge" style="background:#065f46;color:#6ee7b7;font-size:0.6rem;padding:2px 6px;border-radius:3px;font-weight:600;text-transform:uppercase;margin-left:6px;">&#10003; FP Approved</span>'
                            row_style = ' opacity:0.5;background:#111827;'
                        
                        scan_sections_html += f'''
                        <tr class="finding-row" data-group="{group_id}" style="display:none;{row_style}">
                            <td><span class="severity-badge {severity_class}">{sev}</span>{supp_badge}</td>
                            <td>{location}</td>
                            <td>
                                {escape(title)}
                                <div class="finding-type">{ftype}</div>
                                <div class="source-badge" style="margin-top:4px;display:inline-block;background:#334155;color:#a78bfa;font-size:0.7rem;padding:1px 6px;border-radius:3px;">{', '.join(finding.get('sources', ['unknown']))}</div>
                            </td>
                            <td>{message}</td>
                        </tr>'''
                
                scan_sections_html += '''
                    </tbody>
                </table>
'''
            
            scan_sections_html += '''
            </div>
'''
        
        # Generate the full HTML
        from datetime import datetime, timezone
        generated_now = datetime.now()
        generated_time = generated_now.strftime('%Y-%m-%d %H:%M:%S')
        generated_iso = generated_now.isoformat()
        
        html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Security Scan Report</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0d0d0d;
            color: #e0e0e0;
            line-height: 1.6;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: #1a1a1a;
            border-radius: 12px;
            box-shadow: 0 4px 30px rgba(0,0,0,0.5);
            overflow: hidden;
            border: 1px solid #2a2a2a;
        }}
        
        .header {{
            background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #0d1117 100%);
            color: #ffffff;
            padding: 40px;
            text-align: center;
            border-bottom: 2px solid #30363d;
        }}
        
        .header h1 {{
            font-size: 2.5rem;
            margin-bottom: 10px;
            font-weight: 700;
            text-shadow: 0 2px 10px rgba(0,0,0,0.5);
        }}
        
        .header .subtitle {{
            color: #8b949e;
            font-size: 1rem;
        }}
        
        .header .meta {{
            margin-top: 20px;
            display: flex;
            justify-content: center;
            gap: 40px;
            font-size: 0.9rem;
            color: #c9d1d9;
        }}
        
        .summary-section {{
            background: #161b22;
            padding: 30px 40px;
            border-bottom: 1px solid #30363d;
        }}
        
        .summary-section h2 {{
            color: #f0f6fc;
            margin-bottom: 20px;
            font-size: 1.4rem;
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
        }}
        
        .stat-card {{
            background: #21262d;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            border: 1px solid #30363d;
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
        }}
        
        .stat-card .number {{
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 5px;
        }}
        
        .stat-card .label {{
            color: #8b949e;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .stat-card.critical .number {{ color: #f85149; }}
        .stat-card.high .number {{ color: #f0883e; }}
        .stat-card.medium .number {{ color: #d29922; }}
        .stat-card.low .number {{ color: #3fb950; }}
        
        .scan-section {{
            background: #161b22;
            padding: 30px 40px;
            border-bottom: 1px solid #30363d;
        }}
        
        .scan-section:last-of-type {{
            border-bottom: none;
        }}
        
        .scan-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 25px;
            padding-bottom: 15px;
            border-bottom: 2px solid #30363d;
        }}
        
        .scan-header-left {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        
        .scan-header h3 {{
            color: #f0f6fc;
            font-size: 1.3rem;
            margin: 0;
        }}
        
        .scan-repo-info {{
            display: flex;
            gap: 15px;
            font-size: 0.85rem;
            color: #8b949e;
        }}
        
        .scan-repo-info span {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        
        .scan-meta {{
            display: flex;
            gap: 20px;
            color: #8b949e;
            font-size: 0.9rem;
        }}
        
        .severity-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }}
        
        .severity-badge.critical {{
            background: rgba(248, 81, 73, 0.15);
            color: #f85149;
            border: 1px solid #f85149;
        }}
        
        .severity-badge.high {{
            background: rgba(240, 136, 62, 0.15);
            color: #f0883e;
            border: 1px solid #f0883e;
        }}
        
        .severity-badge.medium {{
            background: rgba(210, 153, 34, 0.15);
            color: #d29922;
            border: 1px solid #d29922;
        }}
        
        .severity-badge.low {{
            background: rgba(63, 185, 80, 0.15);
            color: #3fb950;
            border: 1px solid #3fb950;
        }}
        
        .findings-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
            table-layout: fixed;
        }}
        
        .findings-table th {{
            background: #21262d;
            padding: 12px 15px;
            text-align: left;
            font-weight: 600;
            color: #c9d1d9;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 2px solid #30363d;
        }}
        
        .findings-table td {{
            padding: 15px;
            border-bottom: 1px solid #30363d;
            vertical-align: top;
            color: #c9d1d9;
            word-break: break-word;
            overflow-wrap: break-word;
            white-space: normal;
        }}
        
        .findings-table tr:hover {{
            background: #1f2428;
        }}
        
        .finding-type {{
            font-size: 0.8rem;
            color: #8b949e;
            margin-top: 3px;
        }}
        
        .finding-version {{
            font-size: 0.8rem;
            margin-top: 2px;
            color: #8b949e;
        }}
        
        .finding-group-header {{
            cursor: pointer;
        }}
        
        .finding-group-header td {{
            padding: 10px 15px !important;
            background: #1c2333 !important;
            border-bottom: 2px solid #30363d !important;
        }}
        
        .finding-group-header:hover td {{
            background: #243447 !important;
        }}
        
        .group-toggle-icon {{
            font-size: 0.75rem;
            color: #8b949e;
            width: 16px;
            flex-shrink: 0;
        }}
        
        .group-title-row {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}
        
        .group-name {{
            font-size: 0.95rem;
            font-weight: 700;
            color: #f0f6fc;
            font-family: monospace;
        }}
        
        .group-count {{
            font-size: 0.75rem;
            color: #8b949e;
            background: #21262d;
            padding: 2px 8px;
            border-radius: 10px;
        }}
        
        .no-findings {{
            text-align: center;
            padding: 40px;
            color: #3fb950;
            font-weight: 500;
        }}
        
        .no-findings .icon {{
            font-size: 2rem;
            margin-bottom: 10px;
        }}
        
        .footer {{
            background: #0d1117;
            color: #8b949e;
            padding: 20px 40px;
            text-align: center;
            font-size: 0.85rem;
            border-top: 1px solid #30363d;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🛡️ Security Scan Report</h1>
            <p class="subtitle">Comprehensive security findings across all repositories</p>
            <div class="meta">
                <span>📅 Generated: <span class="scan-timestamp" data-utc="{generated_iso}">{generated_time}</span></span>
                <span>📦 Repos Scanned: {total_repos}</span>
                <span>🔍 Total Findings: {total_findings}</span>
            </div>
        </div>

        <div class="summary-section">
            <h2>📊 Executive Summary</h2>
            <div class="stats-grid">
                <div class="stat-card critical">
                    <div class="number">{severity_totals['CRITICAL']}</div>
                    <div class="label">Critical</div>
                </div>
                <div class="stat-card high">
                    <div class="number">{severity_totals['HIGH']}</div>
                    <div class="label">High</div>
                </div>
                <div class="stat-card medium">
                    <div class="number">{severity_totals['MEDIUM']}</div>
                    <div class="label">Medium</div>
                </div>
                <div class="stat-card low">
                    <div class="number">{severity_totals['LOW']}</div>
                    <div class="label">Low</div>
                </div>
            </div>
        </div>

        {scan_sections_html}

        <div class="footer">
            <p>Report generated by <strong>VIRTUAL_PLUMBER</strong> Scanner</p>
            <p>Tools: OpenGrep | TruffleHog | Trivy (SBOM)</p>
        </div>
    </div>
    <script>
        function toggleGroup(header) {{
            var groupId = header.getAttribute('data-group');
            var rows = document.querySelectorAll('tr.finding-row[data-group="' + groupId + '"]');
            var icon = header.querySelector('.group-toggle-icon');
            var isHidden = rows.length > 0 && rows[0].style.display === 'none';
            for (var i = 0; i < rows.length; i++) {{
                rows[i].style.display = isHidden ? '' : 'none';
            }}
            icon.textContent = isHidden ? '▼' : '▶';
        }}

        // Convert UTC timestamps to local time
        (function() {{
            var items = document.querySelectorAll('.scan-timestamp');
            for (var i = 0; i < items.length; i++) {{
                var el = items[i];
                var utc = el.getAttribute('data-utc');
                if (utc) {{
                    if (utc.indexOf('Z') === -1 && utc.indexOf('+') === -1) {{
                        utc = utc + 'Z';
                    }}
                    var d = new Date(utc);
                    if (!isNaN(d.getTime())) {{
                        el.textContent = d.toLocaleString('en-US', {{
                            month: 'short', day: 'numeric', year: 'numeric',
                            hour: '2-digit', minute: '2-digit'
                        }});
                    }}
                }}
            }}
        }})();
    </script>
</body>
</html>'''
        
        # Create response with HTML content
        log_audit_event(
            action='REPORT_EXPORTED',
            resource_type='report',
            new_value={'total_scans': total_repos, 'total_findings': total_findings,
                       'severity_filter': severity_filter, 'tool_filter': tool_filter,
                       'date_from': date_from, 'date_to': date_to}
        )

        response = make_response(html_content)
        response.headers['Content-Type'] = 'text/html'
        response.headers['Content-Disposition'] = f'attachment; filename="security-report-{datetime.now().strftime("%Y%m%d-%H%M%S")}.html"'
        return response
        
    except Exception as e:
        current_app.logger.exception('Error generating report: %s', e)
        return jsonify({'error': str(e)}), 500


# ============ USER MANAGEMENT ENDPOINTS ============

@bp.route('/api/me')
@require_login
def api_get_current_user():
    """Get current user info"""
    user = get_current_user()
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404
    
    return jsonify({
        'status': 'success',
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'role': user.role,
            'full_name': user.full_name,
            'department': user.department
        }
    })


@bp.route('/api/users', methods=['GET'])
@require_login
@require_role('admin', 'operator')
def api_get_users():
    """Get all users (admin and operator)"""
    from models.database import User
    
    current_user = User.query.get(session.get('user_id'))
    
    if current_user and current_user.role == 'operator':
        # Operator sees: admins + their own created viewers
        users = User.query.filter(
            (User.role == 'admin') | (User.created_by_id == current_user.id)
        ).order_by(User.created_at.desc()).all()
    else:
        users = User.query.order_by(User.created_at.desc()).all()
    
    return jsonify({
        'status': 'success',
        'users': [{
             'id': u.id,
             'username': u.username,
             'email': u.email,
             'role': u.role,
             'full_name': u.full_name,
             'department': u.department,
             'created_at': u.created_at.isoformat() if u.created_at else None,
             'last_login': u.last_login.isoformat() if u.last_login else None
        } for u in users]
    })


@bp.route('/api/users', methods=['POST'])
@require_login
@require_role('admin', 'operator')
def api_create_user():
    """Create a new user (admin can create any, operator can create viewer only)"""
    from models.database import User
    from validators.input_validators import validate_username, validate_email, validate_password_strength

    # Get current user to check permissions
    current_user = User.query.get(session.get('user_id'))

    data = request.get_json()

    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided'}), 400

    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'operator')
    full_name = data.get('full_name', '').strip()
    department = data.get('department', '').strip()

    # Validation
    if not username:
        return jsonify({'status': 'error', 'message': 'Username is required'}), 400

    valid, msg = validate_username(username)
    if not valid:
        return jsonify({'status': 'error', 'message': msg}), 400

    if not password:
        return jsonify({'status': 'error', 'message': 'Password is required'}), 400

    valid, msg = validate_password_strength(password, username)
    if not valid:
        return jsonify({'status': 'error', 'message': msg}), 400

    # Check if username exists
    if User.query.filter_by(username=username).first():
        return jsonify({'status': 'error', 'message': 'Username already exists'}), 400

    # Check if email exists
    if email and User.query.filter_by(email=email).first():
        return jsonify({'status': 'error', 'message': 'Email already exists'}), 400

    # Validate role based on current user's permission
    allowed_roles = []
    if current_user.role == 'admin':
        allowed_roles = ['admin', 'operator', 'viewer']
    elif current_user.role == 'operator':
        allowed_roles = ['viewer']  # Operator can only create viewers

    if role not in allowed_roles:
        role = allowed_roles[0] if allowed_roles else 'viewer'
    
    try:
        # Create user
        new_user = User(
            username=username,
            email=email if email else None,
            password_hash=User.hash_password(password),
            role=role,
            full_name=full_name if full_name else None,
            department=department if department else None,
            created_by_id=current_user.id,
            is_first_login=True
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        current_app.logger.debug(f'User {username} created by admin')
        log_audit_event(
            action='USER_CREATED',
            resource_type='user',
            resource_id=new_user.id,
            new_value={'username': username, 'role': role, 'email': email, 'full_name': full_name, 'department': department}
        )
        
        return jsonify({
            'status': 'success',
            'message': f'User {username} created successfully',
            'user': {
                'id': new_user.id,
                'username': new_user.username,
                'role': new_user.role
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/api/users/<int:user_id>', methods=['PUT'])
@require_login
def api_update_user(user_id):
    """Update user (admin can edit any, operator can edit viewers)"""
    from models.database import User
    
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 401
    
    target_user = User.query.get(user_id)
    if not target_user:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404
    
    # Permission check
    if current_user.role == 'admin':
        pass  # Admin can edit any user
    elif current_user.role == 'operator' and target_user.role == 'viewer' and target_user.created_by_id == current_user.id:
        pass  # Operator can edit only their own viewers
    else:
        return jsonify({'error': 'Admin access required', 'code': 'FORBIDDEN'}), 403
    
    data = request.get_json()
    
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided'}), 400
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404
    
    # Track old values for audit
    old_values = {'username': user.username, 'role': user.role, 'email': user.email, 'full_name': user.full_name, 'department': user.department}
    
    # Update fields
    if 'email' in data and data['email']:
        if User.query.filter(User.email == data['email'], User.id != user_id).first():
            return jsonify({'status': 'error', 'message': 'Email already in use'}), 400
        user.email = data['email']
    
    if 'role' in data and data['role'] in ['admin', 'viewer', 'operator']:
        user.role = data['role']
    
    if 'full_name' in data:
        user.full_name = data['full_name'] if data['full_name'] else None
    
    if 'department' in data:
        user.department = data['department'] if data['department'] else None
    
    try:
        db.session.commit()
        current_app.logger.debug(f'User {user.username} updated by admin')
        log_audit_event(
            action='USER_UPDATED',
            resource_type='user',
            resource_id=user_id,
            old_value=old_values,
            new_value={'username': user.username, 'role': user.role, 'email': user.email, 'full_name': user.full_name, 'department': user.department}
        )
        
        return jsonify({
            'status': 'success',
            'message': 'User updated successfully'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/api/users/<int:user_id>', methods=['DELETE'])
@require_login
def api_delete_user(user_id):
    """Delete a user (admin can delete any, operator can delete viewers)"""
    from models.database import User
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404
    
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'User not found'}), 401
    
    # Permission check
    if current_user.role == 'admin':
        pass  # Admin can delete any user
    elif current_user.role == 'operator' and user.role == 'viewer' and user.created_by_id == current_user.id:
        pass  # Operator can delete only their own viewers
    else:
        return jsonify({'error': 'Admin access required', 'code': 'FORBIDDEN'}), 403
    
    # Prevent deleting yourself
    
    try:
        deleted_username = user.username
        deleted_role = user.role
        db.session.delete(user)
        db.session.commit()
        current_app.logger.debug(f'User {deleted_username} deleted by admin')
        log_audit_event(
            action='USER_DELETED',
            resource_type='user',
            resource_id=user_id,
            old_value={'username': deleted_username, 'role': deleted_role}
        )
        
        return jsonify({
            'status': 'success',
            'message': f'User {deleted_username} has been deleted'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============ FALSE POSITIVE MANAGEMENT PAGE ============

@bp.route('/false-positives')
@require_login
def fp_management_page():
    """False Positive Management dashboard page"""
    return render_template('fp_dashboard.html')

# ============ GITHUB WEBHOOK LISTENER ============

@bp.route('/github/webhook', methods=['POST'])
def github_webhook():
    """
    GitHub Webhook endpoint - receives webhook events from GitHub App
    Verifies signature and processes events
    
    Returns:
        JSON response with status
    """
    from modules.env_config import env_config
    
    try:
        # Get the webhook secret from .env
        webhook_secret = env_config.get_github_credentials().get('github_webhook_secret', '')
        
        if not webhook_secret:
            current_app.logger.warning('GitHub webhook received but GITHUB_WEBHOOK_SECRET not configured')
            return jsonify({'status': 'error', 'message': 'Webhook secret not configured'}), 400
        
        # Verify webhook signature
        signature_header = request.headers.get('X-Hub-Signature-256', '')
        
        if not signature_header:
            current_app.logger.warning('GitHub webhook received without signature header')
            return jsonify({'status': 'error', 'message': 'No signature provided'}), 400
        
        # Get raw body for signature verification
        body = request.get_data()
        
        # Compute HMAC-SHA256
        computed_signature = 'sha256=' + hmac.new(
            webhook_secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        
        # Verify signature
        if not hmac.compare_digest(signature_header, computed_signature):
            current_app.logger.warning(f'GitHub webhook signature verification failed')
            return jsonify({'status': 'error', 'message': 'Signature verification failed'}), 403
        
        # Parse JSON payload
        payload = request.get_json()
        
        if not payload:
            return jsonify({'status': 'error', 'message': 'No JSON payload'}), 400
        
        # Get event type from headers
        event_type = request.headers.get('X-GitHub-Event', 'unknown')
        
        # Log the webhook event
        current_app.logger.info(f'GitHub webhook received: {event_type}')
        current_app.logger.debug(f'Webhook payload: {json.dumps(payload, indent=2)}')
        
        # Handle different event types
        if event_type == 'pull_request':
            return handle_pr_webhook(payload)
        elif event_type == 'push':
            return handle_push_webhook(payload)
        elif event_type == 'issues':
            return handle_issues_webhook(payload)
        elif event_type == 'ping':
            return jsonify({'status': 'success', 'message': 'Webhook configured successfully'}), 200
        else:
            current_app.logger.debug(f'Unhandled webhook event type: {event_type}')
            return jsonify({'status': 'success', 'message': f'Event type {event_type} received but not processed'}), 200
    
    except Exception as e:
        current_app.logger.error(f'Error processing GitHub webhook: {str(e)}')
        return jsonify({'status': 'error', 'message': f'Error processing webhook: {str(e)}'}), 500


def handle_pr_webhook(payload):
    """
    Handle pull_request events from GitHub webhook
    Automatically triggers security scans on PR open and synchronize events
    
    Args:
        payload: GitHub webhook payload
    
    Returns:
        JSON response with status
    """
    try:
        from modules.pr_scan_handler import trigger_pr_scan
        from modules.repos import get_repositories
        
        action = payload.get('action', '')
        pr = payload.get('pull_request', {})
        repo = payload.get('repository', {})
        
        pr_number = pr.get('number', 'unknown')
        pr_title = pr.get('title', '')
        pr_head_sha = pr.get('head', {}).get('sha', '')
        repo_name = repo.get('name', 'unknown')
        repo_owner = repo.get('owner', {}).get('login', 'unknown')
        repo_id = repo.get('id', '')
        repo_url = repo.get('clone_url', f'https://github.com/{repo_owner}/{repo_name}.git')
        
        current_app.logger.info(f'Pull Request {action}: {repo_owner}/{repo_name}#{pr_number} - {pr_title}')
        
        pr_head = pr.get('head', {})
        repo_branch = pr_head.get('ref', 'main')
        
        current_app.logger.info(f'PR #{pr_number} source branch (head): {repo_branch}')
        
        # Get admin user for settings check
        from models.database import User
        admin_user = User.query.filter_by(role='admin').first()
        pr_scan_enabled = admin_user.pr_scan_enabled if admin_user else True
        pr_block_enabled = admin_user.pr_block_enabled if admin_user else False
        pr_block_severity = (admin_user.pr_block_severity or 'HIGH') if admin_user else 'HIGH'
        
        current_app.logger.info(f'PR scan enabled: {pr_scan_enabled}, block: {pr_block_enabled}, threshold: {pr_block_severity}')
        
        # Handle different PR actions
        if action in ['opened', 'reopened', 'synchronize']:
            current_app.logger.info(f'PR #{pr_number} in {repo_owner}/{repo_name}, triggering scan...')
            
            log_audit_event(
                action='PR_WEBHOOK_RECEIVED',
                resource_type='pull_request',
                resource_id=f'{repo_owner}/{repo_name}#{pr_number}',
                new_value={'action': action, 'pr_number': pr_number,
                          'repo': f'{repo_owner}/{repo_name}', 'pr_title': pr_title}
            )
            
            if not pr_scan_enabled:
                current_app.logger.info(f'PR scan is disabled - skipping scan for PR #{pr_number}')
                return jsonify({
                    'status': 'success',
                    'message': f'PR #{pr_number} received, scanning disabled',
                    'pr_number': pr_number,
                    'repo': f'{repo_owner}/{repo_name}',
                    'scan_status': 'skipped'
                }), 200
            
            # Trigger security scan
            scan_result = trigger_pr_scan(
                repo_id=repo_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
                repo_url=repo_url,
                pr_number=pr_number,
                pr_title=pr_title,
                pr_head_sha=pr_head_sha,
                scan_types=['sats', 'sbom', 'secret', 'snyk'],
                repo_branch=repo_branch,
                pr_block_enabled=pr_block_enabled,
                pr_block_severity=pr_block_severity
            )
            
            current_app.logger.info(f'PR scan triggered: {scan_result.get("scan_id")}')
            
            return jsonify({
                'status': 'success',
                'message': f'PR #{pr_number} opened, scan triggered',
                'pr_number': pr_number,
                'repo': f'{repo_owner}/{repo_name}',
                'scan_id': scan_result.get('scan_id'),
                'scan_status': 'pending'
            }), 200
        
        elif action == 'closed':
            current_app.logger.info(f'PR #{pr_number} closed')
            # Could archive/cleanup PR scan results here if needed
            
            return jsonify({
                'status': 'success',
                'message': f'PR #{pr_number} closed',
                'pr_number': pr_number,
                'repo': f'{repo_owner}/{repo_name}'
            }), 200
        
        else:
            # Other PR actions (edited, assigned, labeled, etc.) - no action needed
            return jsonify({
                'status': 'success',
                'message': f'PR event {action} received but not processed',
                'pr_number': pr_number,
                'repo': f'{repo_owner}/{repo_name}'
            }), 200
    
    except Exception as e:
        current_app.logger.error(f'Error handling PR webhook: {str(e)}')
        import traceback
        current_app.logger.exception(traceback.format_exc())
        return jsonify({'status': 'error', 'message': str(e)}), 500


def handle_push_webhook(payload):
    """
    Handle push events from GitHub webhook
    
    Args:
        payload: GitHub webhook payload
    
    Returns:
        JSON response with status
    """
    try:
        repo = payload.get('repository', {})
        ref = payload.get('ref', '')
        branch = ref.replace('refs/heads/', '')
        
        repo_name = repo.get('name', 'unknown')
        repo_owner = repo.get('owner', {}).get('login', 'unknown')
        
        current_app.logger.info(f'Push to {repo_owner}/{repo_name}:{branch}')
        
        return jsonify({
            'status': 'success',
            'message': f'Push event processed',
            'repo': f'{repo_owner}/{repo_name}',
            'branch': branch
        }), 200
    
    except Exception as e:
        current_app.logger.error(f'Error handling push webhook: {str(e)}')
        return jsonify({'status': 'error', 'message': str(e)}), 500


def handle_issues_webhook(payload):
    """
    Handle issues events from GitHub webhook
    
    Args:
        payload: GitHub webhook payload
    
    Returns:
        JSON response with status
    """
    try:
        action = payload.get('action', '')
        issue = payload.get('issue', {})
        repo = payload.get('repository', {})
        
        issue_number = issue.get('number', 'unknown')
        issue_title = issue.get('title', '')
        repo_name = repo.get('name', 'unknown')
        repo_owner = repo.get('owner', {}).get('login', 'unknown')
        
        current_app.logger.info(f'Issue {action}: {repo_owner}/{repo_name}#{issue_number} - {issue_title}')
        
        return jsonify({
            'status': 'success',
            'message': f'Issue event {action} processed',
            'issue_number': issue_number,
            'repo': f'{repo_owner}/{repo_name}'
        }), 200
    
    except Exception as e:
        current_app.logger.error(f'Error handling issues webhook: {str(e)}')
        return jsonify({'status': 'error', 'message': str(e)}), 500
