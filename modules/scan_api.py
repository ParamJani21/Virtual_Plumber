from flask import Blueprint, request, jsonify, current_app
import logging

from modules.scan_controller import trigger_scan, get_cloned_repos, cleanup_cloned_repo

bp = Blueprint('scan_api', __name__)
logger = logging.getLogger(__name__)


@bp.route('/api/scan', methods=['POST'])
def api_trigger_scan():
    """Trigger repository scan (uses GitHub App installation token to clone).

    Expects JSON: { repo_id, repo_name, repo_owner, repo_url (optional), repo_branch (optional) }
    """
    try:
        payload = request.get_json(silent=True) or {}
        repo_id = payload.get('repo_id')
        repo_name = payload.get('repo_name')
        repo_owner = payload.get('repo_owner')
        repo_url = payload.get('repo_url')
        repo_branch = payload.get('repo_branch', 'main')

        if not repo_id:
            return jsonify({'status': 'error', 'message': 'repo_id is required'}), 400
        if not repo_name or not repo_owner:
            return jsonify({'status': 'error', 'message': 'repo_name and repo_owner are required'}), 400

        if not repo_url:
            repo_url = f'https://github.com/{repo_owner}/{repo_name}.git'

        current_app.logger.debug('API scan requested for %s/%s (id=%s)', repo_owner, repo_name, repo_id)

        result = trigger_scan(repo_id, repo_name, repo_owner, repo_url, repo_branch)

        if result.get('status') == 'success':
            return jsonify(result), 200
        else:
            current_app.logger.error('Scan failed: %s', result.get('message'))
            return jsonify(result), 500

    except Exception as exc:
        current_app.logger.exception('Error in api_trigger_scan: %s', exc)
        return jsonify({'status': 'error', 'message': str(exc)}), 500


@bp.route('/api/scan/cloned', methods=['GET'])
def api_list_cloned():
    """List cloned repositories in the work directory."""
    try:
        repos = get_cloned_repos()
        return jsonify({'status': 'success', 'cloned': repos}), 200
    except Exception as exc:
        logger.exception('Error listing cloned repos: %s', exc)
        return jsonify({'status': 'error', 'message': str(exc)}), 500


@bp.route('/api/scan/cleanup', methods=['POST'])
def api_cleanup_cloned():
    """Cleanup a cloned repository. Expects JSON: { repo_owner, repo_name, scan_id (optional) }"""
    try:
        payload = request.get_json(silent=True) or {}
        repo_owner = payload.get('repo_owner')
        repo_name = payload.get('repo_name')
        scan_id = payload.get('scan_id')

        if not repo_owner or not repo_name:
            return jsonify({'status': 'error', 'message': 'repo_owner and repo_name are required'}), 400

        ok = cleanup_cloned_repo(repo_owner, repo_name, scan_id=scan_id)
        if ok:
            return jsonify({'status': 'success', 'message': 'Cleanup successful'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Path not found or cleanup failed'}), 404

    except Exception as exc:
        logger.exception('Error cleaning up cloned repo: %s', exc)
        return jsonify({'status': 'error', 'message': str(exc)}), 500
