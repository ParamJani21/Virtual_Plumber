from flask import Blueprint, jsonify, request, current_app
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth.decorators import require_login
from auth.utils import get_current_user
from modules.fp_manager import (
    submit_fp_request, approve_fp_request, reject_fp_request,
    revert_fp_to_tp, get_fp_requests, get_fp_request_detail,
    get_fp_review_queue, check_fingerprint_suppressed,
    apply_suppressions_to_findings
)

fp_bp = Blueprint('fp', __name__)


@fp_bp.route('/api/fp/requests', methods=['GET'])
@require_login
def list_fp_requests():
    """List FP requests with optional status filter and pagination"""
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 401

        status = request.args.get('status')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        result = get_fp_requests(user.id, user.role, status, page, per_page)
        return jsonify(result)
    except Exception as e:
        current_app.logger.error('Error listing FP requests: %s', e)
        return jsonify({'error': 'Internal server error'}), 500


@fp_bp.route('/api/fp/requests', methods=['POST'])
@require_login
def submit_fp_request_route():
    """Submit a new false positive request"""
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 401

        data = request.get_json(force=True)
        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        finding = data.get('finding')
        viewer_reason = data.get('viewer_reason')
        scan_metadata = data.get('scan_metadata', {})

        if not finding:
            return jsonify({'error': 'finding is required'}), 400
        if not viewer_reason or not isinstance(viewer_reason, str) or not viewer_reason.strip():
            return jsonify({'error': 'viewer_reason is required and must be a non-empty string'}), 400

        result = submit_fp_request(finding, user.id, viewer_reason, scan_metadata, submitter_role=user.role)

        return jsonify(result), 201 if result.get('success') else 200
    except Exception as e:
        current_app.logger.error('Error submitting FP request: %s', e)
        return jsonify({'error': 'Internal server error'}), 500


@fp_bp.route('/api/fp/requests/<int:request_id>', methods=['GET'])
@require_login
def get_fp_request_detail_route(request_id):
    """Get detailed information about a specific FP request"""
    try:
        result = get_fp_request_detail(request_id)
        if not result:
            return jsonify({'error': 'FP request not found'}), 404
        return jsonify(result)
    except Exception as e:
        current_app.logger.error('Error getting FP request detail: %s', e)
        return jsonify({'error': 'Internal server error'}), 500


@fp_bp.route('/api/fp/requests/<int:request_id>/approve', methods=['POST'])
@require_login
def approve_fp_request_route(request_id):
    """Approve a false positive request"""
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 401

        if user.role not in ('operator', 'admin'):
            return jsonify({'error': 'Only operators and admins can approve FP requests'}), 403

        data = request.get_json(silent=True) or {}
        message = data.get('message')

        result = approve_fp_request(request_id, user.id, user.role, message)

        return jsonify(result)
    except Exception as e:
        current_app.logger.error('Error approving FP request: %s', e)
        return jsonify({'error': 'Internal server error'}), 500


@fp_bp.route('/api/fp/requests/<int:request_id>/reject', methods=['POST'])
@require_login
def reject_fp_request_route(request_id):
    """Reject a false positive request"""
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 401

        if user.role not in ('operator', 'admin'):
            return jsonify({'error': 'Only operators and admins can reject FP requests'}), 403

        data = request.get_json(force=True)
        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        message = data.get('message')
        if not message or not isinstance(message, str) or not message.strip():
            return jsonify({'error': 'message is required and must be a non-empty string'}), 400

        result = reject_fp_request(request_id, user.id, user.role, message)

        return jsonify(result)
    except Exception as e:
        current_app.logger.error('Error rejecting FP request: %s', e)
        return jsonify({'error': 'Internal server error'}), 500


@fp_bp.route('/api/fp/requests/<int:request_id>/revert', methods=['POST'])
@require_login
def revert_fp_request_route(request_id):
    """Revert a false positive back to true positive (admin only)"""
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 401

        if user.role != 'admin':
            return jsonify({'error': 'Only admins can revert FP requests'}), 403

        data = request.get_json(silent=True) or {}
        message = data.get('message')

        result = revert_fp_to_tp(request_id, user.id, message)

        return jsonify(result)
    except Exception as e:
        current_app.logger.error('Error reverting FP request: %s', e)
        return jsonify({'error': 'Internal server error'}), 500


@fp_bp.route('/api/fp/pending-count', methods=['GET'])
@require_login
def fp_pending_count():
    """Lightweight endpoint for pending FP review count (for notification badge)"""
    try:
        user = get_current_user()
        if not user:
            return jsonify({'count': 0}), 200
        if user.role not in ('operator', 'admin'):
            return jsonify({'count': 0}), 200

        from models.false_positive import FalsePositiveRecord
        from models.database import User
        if user.role == 'operator':
            my_viewer_ids = [u.id for u in User.query.filter_by(created_by_id=user.id).all()]
            if my_viewer_ids:
                count = FalsePositiveRecord.query.filter(
                    FalsePositiveRecord.status == 'PENDING_OPERATOR',
                    FalsePositiveRecord.created_by_viewer_id.in_(my_viewer_ids)
                ).count()
            else:
                count = 0
        else:
            count = FalsePositiveRecord.query.filter_by(status='PENDING_ADMIN').count()
        return jsonify({'count': count})
    except Exception as e:
        current_app.logger.error('Error getting pending FP count: %s', e)
        return jsonify({'count': 0}), 200


@fp_bp.route('/api/fp/queue', methods=['GET'])
@require_login
def get_review_queue():
    """Get the current user's review queue"""
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 401

        if user.role not in ('operator', 'admin'):
            return jsonify({'error': 'Only operators and admins have a review queue'}), 403

        result = get_fp_review_queue(user.id, user.role)
        return jsonify(result)
    except Exception as e:
        current_app.logger.error('Error getting review queue: %s', e)
        return jsonify({'error': 'Internal server error'}), 500


@fp_bp.route('/api/fp/check/<fingerprint>', methods=['GET'])
@require_login
def check_fingerprint(fingerprint):
    """Check if a fingerprint is suppressed"""
    try:
        suppressed, record_id = check_fingerprint_suppressed(fingerprint)
        return jsonify({'suppressed': suppressed, 'record_id': record_id})
    except Exception as e:
        current_app.logger.error('Error checking fingerprint: %s', e)
        return jsonify({'error': 'Internal server error'}), 500


@fp_bp.route('/api/fp/batch-check', methods=['POST'])
@require_login
def batch_check_fingerprints():
    """Check multiple fingerprints for suppression"""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        fingerprints = data.get('fingerprints', [])
        if not fingerprints or not isinstance(fingerprints, list):
            return jsonify({'error': 'fingerprints must be a non-empty list'}), 400

        results = []
        for fp in fingerprints:
            suppressed, record_id = check_fingerprint_suppressed(fp)
            results.append({
                'fingerprint': fp,
                'suppressed': suppressed,
                'record_id': record_id
            })

        return jsonify({'results': results})
    except Exception as e:
        current_app.logger.error('Error batch checking fingerprints: %s', e)
        return jsonify({'error': 'Internal server error'}), 500
