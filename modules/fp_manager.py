"""
False Positive Management Module
Human-Governed Vulnerability Suppression Workflow

Implements the 3-tier (Viewer → Operator → Admin) approval chain
for marking security findings as false positives.

Status lifecycle:
    PENDING_OPERATOR → (reject → OPERATOR_REJECTED | approve → PENDING_ADMIN)
    PENDING_ADMIN → (reject → ADMIN_REJECTED | approve → APPROVED_FP)
    APPROVED_FP → (revert → REVERTED_TO_TP)
"""

import json
import logging
from datetime import datetime
from models.database import db
from models.false_positive import FalsePositiveRecord
from utils.fingerprint import generate_fingerprint, fp_fingerprint_from_finding
from auth.utils import log_audit_event

logger = logging.getLogger(__name__)


# ============================================================
# SUBMIT
# ============================================================

def submit_fp_request(finding, submitter_id, viewer_reason, scan_metadata=None, submitter_role=None):
    """
    Submit a finding as suspected false positive.
    
    Approval chain depends on submitter role:
    - viewer: PENDING_OPERATOR → operator approves → PENDING_ADMIN → admin approves → APPROVED_FP
    - operator: PENDING_ADMIN → admin approves → APPROVED_FP
    - admin: APPROVED_FP (immediate)
    
    Args:
        finding: Finding dict from merged.json
        submitter_id: ID of the user submitting
        viewer_reason: Justification text
        scan_metadata: Optional dict with repo_name, branch_name, etc.
        submitter_role: Role of the submitter (viewer/operator/admin). 
                        If None, looked up from DB.
    
    Returns:
        Dict with {'success': bool, 'request': dict or None, 'error': str}
    """
    try:
        from models.database import User
        submitter = db.session.get(User, submitter_id)
        if not submitter:
            return {'success': False, 'error': 'Submitter not found'}
        
        role = submitter_role or submitter.role
        
        # Generate fingerprint
        fp = fp_fingerprint_from_finding(finding)
        
        # Check if already submitted
        existing = FalsePositiveRecord.query.filter_by(fingerprint=fp).first()
        if existing and existing.status not in ('REVERTED_TO_TP', 'OPERATOR_REJECTED', 'ADMIN_REJECTED'):
            return {
                'success': False, 
                'error': 'This finding already has a FP request',
                'existing_status': existing.status,
                'existing_id': existing.id
            }
        
        # Determine whether to reuse existing record or create new
        is_resubmit = existing is not None
        
        # Determine source tool
        sources = finding.get('sources', ['unknown'])
        tool_name = scan_metadata.get('tool_name', sources[0]) if scan_metadata else sources[0]
        
        # Build common record fields
        now = datetime.utcnow()
        record_kwargs = dict(
            fingerprint=fp,
            repo_name=scan_metadata.get('repo_name') if scan_metadata else None,
            branch_name=scan_metadata.get('branch_name') if scan_metadata else None,
            commit_hash=scan_metadata.get('commit_hash') if scan_metadata else None,
            tool_name=tool_name,
            finding_type=finding.get('type'),
            severity=finding.get('severity'),
            cwe=','.join(finding.get('cwe', [])) if finding.get('cwe') else scan_metadata.get('cwe') if scan_metadata else None,
            file_path=finding.get('file'),
            line_number=finding.get('line'),
            matched_code=scan_metadata.get('matched_code') if scan_metadata else None,
            code_context=scan_metadata.get('code_context') if scan_metadata else None,
            scanner_message=finding.get('message'),
            remediation=scan_metadata.get('remediation') if scan_metadata else None,
            created_by_viewer_id=submitter_id,
            viewer_reason=viewer_reason,
            created_at=now
        )
        
        if role == 'admin':
            # Admin: immediately approved
            escalation = [{
                'from_role': 'admin',
                'to_role': 'system',
                'timestamp': now.isoformat(),
                'message': viewer_reason,
                'user_id': submitter_id
            }]
            record_kwargs['status'] = 'APPROVED_FP'
            record_kwargs['approved_by_admin_id'] = submitter_id
            record_kwargs['approved_at'] = now
            record_kwargs['escalation_history'] = json.dumps(escalation)
            
        elif role == 'operator':
            # Operator: skip operator review, go directly to PENDING_ADMIN
            escalation = [{
                'from_role': 'operator',
                'to_role': 'admin',
                'timestamp': now.isoformat(),
                'message': viewer_reason,
                'user_id': submitter_id
            }]
            record_kwargs['status'] = 'PENDING_ADMIN'
            record_kwargs['operator_message'] = viewer_reason
            record_kwargs['approved_by_operator_id'] = submitter_id
            record_kwargs['escalation_history'] = json.dumps(escalation)
            
        else:
            # Viewer: PENDING_OPERATOR, assign an operator for review
            operator = User.query.filter_by(role='operator').first()
            if not operator:
                operator = User.query.filter_by(role='admin').first()
            escalation = [{
                'from_role': 'viewer',
                'to_role': 'operator',
                'timestamp': now.isoformat(),
                'message': viewer_reason,
                'user_id': submitter_id
            }]
            record_kwargs['operator_id'] = operator.id if operator else None
            record_kwargs['status'] = 'PENDING_OPERATOR'
            record_kwargs['escalation_history'] = json.dumps(escalation)

        # Reset reversion fields for resubmit
        if is_resubmit:
            record_kwargs['reverted_to_tp'] = 0
            record_kwargs['reverted_at'] = None
        
        if is_resubmit:
            # Update existing record (clear old workflow fields)
            for key, value in record_kwargs.items():
                setattr(existing, key, value)
            existing.operator_id = None
            existing.operator_message = None
            existing.admin_message = None
            existing.approved_by_operator_id = None
            existing.approved_by_admin_id = None
            existing.approved_at = None
            existing.updated_at = now
            record = existing
        else:
            record = FalsePositiveRecord(**record_kwargs)
            db.session.add(record)
        db.session.commit()
        
        # Audit log
        log_audit_event(
            user_id=submitter_id,
            action='FP_REQUEST_SUBMITTED',
            resource_type='false_positive',
            resource_id=str(record.id),
            new_value={
                'fingerprint': fp,
                'reason': viewer_reason,
                'submitter_role': role,
                'file': finding.get('file', ''),
                'title': finding.get('title', ''),
                'severity': finding.get('severity', ''),
                'finding_type': finding.get('type', ''),
                'tool_name': tool_name or ''
            },
            username=submitter.username,
            user_role=role
        )
        
        logger.info(f'FP request #{record.id} submitted by {role} {submitter_id} for fingerprint {fp[:16]}...')
        
        return {'success': True, 'request': record.to_dict()}
    
    except Exception as e:
        db.session.rollback()
        logger.exception(f'Error submitting FP request: {e}')
        return {'success': False, 'error': str(e)}


# ============================================================
# APPROVE
# ============================================================

def approve_fp_request(request_id, reviewer_id, reviewer_role, message=None):
    """
    Approve a pending FP request.
    
    - Operator approval: PENDING_OPERATOR → PENDING_ADMIN (escalates to admin)
    - Admin approval: PENDING_ADMIN → APPROVED_FP (final approval)
    
    Args:
        request_id: ID of the FP request
        reviewer_id: ID of the reviewer
        reviewer_role: 'operator' or 'admin'
        message: Optional review message
    
    Returns:
        Dict with result
    """
    try:
        record = db.session.get(FalsePositiveRecord, request_id)
        if not record:
            return {'success': False, 'error': 'FP request not found'}
        
        from models.database import User
        reviewer = db.session.get(User, reviewer_id)
        if not reviewer:
            return {'success': False, 'error': 'Reviewer not found'}
        
        if reviewer_role == 'operator':
            if record.status != 'PENDING_OPERATOR':
                return {'success': False, 'error': f'Cannot approve: current status is {record.status}. Expected PENDING_OPERATOR.'}
            
            # Parse existing escalation history
            escalation = json.loads(record.escalation_history) if record.escalation_history else []
            escalation.append({
                'from_role': 'operator',
                'to_role': 'admin',
                'timestamp': datetime.utcnow().isoformat(),
                'message': message or '',
                'user_id': reviewer_id
            })
            
            record.status = 'PENDING_ADMIN'
            record.operator_message = message
            record.approved_by_operator_id = reviewer_id
            record.escalation_history = json.dumps(escalation)
            
            action = 'FP_APPROVED_BY_OPERATOR'
            new_val = {'status': 'PENDING_ADMIN', 'operator_message': message}
            
        elif reviewer_role == 'admin':
            if record.status != 'PENDING_ADMIN':
                return {'success': False, 'error': f'Cannot approve: current status is {record.status}. Expected PENDING_ADMIN.'}
            
            # Parse existing escalation history
            escalation = json.loads(record.escalation_history) if record.escalation_history else []
            escalation.append({
                'from_role': 'admin',
                'to_role': 'system',
                'timestamp': datetime.utcnow().isoformat(),
                'message': message or '',
                'user_id': reviewer_id
            })
            
            record.status = 'APPROVED_FP'
            record.admin_message = message
            record.approved_by_admin_id = reviewer_id
            record.approved_at = datetime.utcnow()
            record.escalation_history = json.dumps(escalation)
            
            action = 'FP_APPROVED_BY_ADMIN'
            new_val = {'status': 'APPROVED_FP', 'admin_message': message}
        else:
            return {'success': False, 'error': f'Invalid role: {reviewer_role}'}
        
        db.session.commit()
        
        log_audit_event(
            user_id=reviewer_id,
            action=action,
            resource_type='false_positive',
            resource_id=str(record.id),
            new_value={**new_val, 'file': record.file_path, 'title': record.finding_type, 'severity': record.severity},
            username=reviewer.username,
            user_role=reviewer_role
        )
        
        logger.info(f'FP request #{record.id} approved by {reviewer_role} {reviewer_id}')
        
        return {'success': True, 'request': record.to_dict()}
    
    except Exception as e:
        db.session.rollback()
        logger.exception(f'Error approving FP request: {e}')
        return {'success': False, 'error': str(e)}


# ============================================================
# REJECT
# ============================================================

def reject_fp_request(request_id, reviewer_id, reviewer_role, message):
    """
    Reject a pending FP request at any stage.
    
    - Operator rejects: PENDING_OPERATOR → OPERATOR_REJECTED
    - Admin rejects: PENDING_ADMIN → ADMIN_REJECTED
    
    Args:
        request_id: ID of the FP request
        reviewer_id: ID of the reviewer
        reviewer_role: 'operator' or 'admin'
        message: Rejection reason (required)
    
    Returns:
        Dict with result
    """
    if not message or not message.strip():
        return {'success': False, 'error': 'Rejection requires a message'}
    
    try:
        record = db.session.get(FalsePositiveRecord, request_id)
        if not record:
            return {'success': False, 'error': 'FP request not found'}
        
        from models.database import User
        reviewer = db.session.get(User, reviewer_id)
        if not reviewer:
            return {'success': False, 'error': 'Reviewer not found'}
        
        if reviewer_role == 'operator':
            if record.status != 'PENDING_OPERATOR':
                return {'success': False, 'error': f'Cannot reject: current status is {record.status}'}
            record.status = 'OPERATOR_REJECTED'
            record.operator_message = message
            action = 'FP_REJECTED_BY_OPERATOR'
        elif reviewer_role == 'admin':
            if record.status not in ('PENDING_ADMIN', 'PENDING_OPERATOR'):
                return {'success': False, 'error': f'Cannot reject: current status is {record.status}'}
            record.status = 'ADMIN_REJECTED'
            record.admin_message = message
            action = 'FP_REJECTED_BY_ADMIN'
        else:
            return {'success': False, 'error': f'Invalid role: {reviewer_role}'}
        
        # Add to escalation history
        escalation = json.loads(record.escalation_history) if record.escalation_history else []
        escalation.append({
            'from_role': reviewer_role,
            'to_role': 'rejected',
            'timestamp': datetime.utcnow().isoformat(),
            'message': message,
            'user_id': reviewer_id
        })
        record.escalation_history = json.dumps(escalation)
        
        db.session.commit()
        
        log_audit_event(
            user_id=reviewer_id,
            action=action,
            resource_type='false_positive',
            resource_id=str(record.id),
            new_value={'status': record.status, 'reason': message, 'file': record.file_path, 'title': record.finding_type, 'severity': record.severity},
            username=reviewer.username,
            user_role=reviewer_role
        )
        
        logger.info(f'FP request #{record.id} rejected by {reviewer_role} {reviewer_id}: {message[:50]}')
        
        return {'success': True, 'request': record.to_dict()}
    
    except Exception as e:
        db.session.rollback()
        logger.exception(f'Error rejecting FP request: {e}')
        return {'success': False, 'error': str(e)}


# ============================================================
# REVERT TO TP
# ============================================================

def revert_fp_to_tp(request_id, admin_id, message=None):
    """
    Admin reverts an APPROVED_FP back to REVERTED_TO_TP.
    
    Once reverted, the finding will no longer be suppressed.
    
    Args:
        request_id: ID of the FP request
        admin_id: ID of the admin performing the revert
        message: Optional reason for reverting
    
    Returns:
        Dict with result
    """
    try:
        record = db.session.get(FalsePositiveRecord, request_id)
        if not record:
            return {'success': False, 'error': 'FP request not found'}
        
        if record.status != 'APPROVED_FP':
            return {'success': False, 'error': f'Cannot revert: current status is {record.status}. Expected APPROVED_FP.'}
        
        from models.database import User
        admin = db.session.get(User, admin_id)
        if not admin or admin.role != 'admin':
            return {'success': False, 'error': 'Only admins can revert FP decisions'}
        
        record.status = 'REVERTED_TO_TP'
        record.reverted_to_tp = 1
        record.reverted_at = datetime.utcnow()
        
        escalation = json.loads(record.escalation_history) if record.escalation_history else []
        escalation.append({
            'from_role': 'admin',
            'to_role': 'reverted',
            'timestamp': datetime.utcnow().isoformat(),
            'message': message or 'Reverted to true positive',
            'user_id': admin_id
        })
        record.escalation_history = json.dumps(escalation)
        
        db.session.commit()
        
        log_audit_event(
            user_id=admin_id,
            action='FP_REVERTED_TO_TP',
            resource_type='false_positive',
            resource_id=str(record.id),
            new_value={'status': 'REVERTED_TO_TP', 'file': record.file_path, 'title': record.finding_type, 'severity': record.severity},
            username=admin.username,
            user_role='admin'
        )
        
        logger.info(f'FP request #{record.id} reverted to TP by admin {admin_id}')
        
        return {'success': True, 'request': record.to_dict()}
    
    except Exception as e:
        db.session.rollback()
        logger.exception(f'Error reverting FP: {e}')
        return {'success': False, 'error': str(e)}


# ============================================================
# QUERY
# ============================================================

def get_fp_requests(user_id=None, role=None, status=None, page=1, per_page=20):
    """
    Get FP requests filtered by user role and optional status.
    
    - Viewer: sees only their own requests
    - Operator: sees all requests (or team-filtered with status='team')
    - Admin: sees all requests (or team-filtered with status='team')
    
    Args:
        user_id: Current user's ID
        role: Current user's role
        status: Optional filter by status string ('my', 'team', 'active', 'resolved', or a specific status)
        page: Page number (1-indexed)
        per_page: Items per page
    
    Returns:
        Dict with requests list, pagination info
    """
    try:
        from models.database import User
        
        query = FalsePositiveRecord.query
        
        if status == 'my':
            if user_id:
                query = query.filter_by(created_by_viewer_id=user_id)
        elif status == 'team':
            if user_id and role in ('admin', 'operator'):
                child_ids = [u.id for u in User.query.filter_by(created_by_id=user_id).all()]
                team_ids = [user_id] + child_ids
                query = query.filter(FalsePositiveRecord.created_by_viewer_id.in_(team_ids))
        elif role in ('viewer', 'operator'):
            if user_id:
                query = query.filter_by(created_by_viewer_id=user_id)
        
        if status:
            if status == 'active':
                # Show only non-terminal states
                query = query.filter(FalsePositiveRecord.status.in_(['PENDING_OPERATOR', 'PENDING_ADMIN']))
            elif status == 'resolved':
                query = query.filter(FalsePositiveRecord.status.in_(['APPROVED_FP', 'REVERTED_TO_TP', 'OPERATOR_REJECTED', 'ADMIN_REJECTED']))
            elif status in ('my', 'team'):
                pass  # Already handled above; 'my'/'team' means no additional status filter
            else:
                query = query.filter_by(status=status)
        
        # Order by newest first
        query = query.order_by(FalsePositiveRecord.created_at.desc())
        
        total = query.count()
        records = query.offset((page - 1) * per_page).limit(per_page).all()
        
        return {
            'success': True,
            'requests': [_enrich_fp_record(r) for r in records],
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page if total > 0 else 1
        }
    
    except Exception as e:
        logger.exception(f'Error retrieving FP requests: {e}')
        return {'success': False, 'error': str(e), 'requests': [], 'total': 0}


def _enrich_fp_record(record):
    """
    Enrich a FalsePositiveRecord with resolved usernames and parsed fields.
    
    Args:
        record: FalsePositiveRecord object
    
    Returns:
        Enriched dict
    """
    from models.database import User
    result = record.to_dict()
    
    # Parse escalation history
    if result.get('escalation_history'):
        try:
            result['escalation_history'] = json.loads(result['escalation_history'])
        except (json.JSONDecodeError, TypeError):
            pass
    
    # Resolve usernames
    result['submitter_username'] = None
    if record.created_by_viewer_id:
        u = db.session.get(User, record.created_by_viewer_id)
        if u:
            result['submitter_username'] = u.username
    
    result['resolver_username'] = None
    resolver_id = record.approved_by_admin_id or record.approved_by_operator_id
    if resolver_id:
        u = db.session.get(User, resolver_id)
        if u:
            result['resolver_username'] = u.username
    
    result['operator_username'] = None
    if record.operator_id:
        u = db.session.get(User, record.operator_id)
        if u:
            result['operator_username'] = u.username
    
    # Derive a title from finding_type
    ft = record.finding_type or ''
    result['title'] = ft.replace('_', ' ').title() if ft else 'Unknown Finding'
    
    # Alias escalation_history as history for frontend compatibility
    if result.get('escalation_history') and isinstance(result['escalation_history'], list):
        result['history'] = []
        for entry in result['escalation_history']:
            result['history'].append({
                'action': entry.get('from_role', 'unknown') + ' → ' + entry.get('to_role', 'unknown'),
                'new_status': entry.get('to_role', ''),
                'message': entry.get('message', ''),
                'changed_by_username': str(entry.get('user_id', '')),
                'created_at': entry.get('timestamp', '')
            })
    else:
        result['history'] = []
    
    # Resolution message combines operator + admin notes
    msgs = []
    if record.operator_message:
        msgs.append(record.operator_message)
    if record.admin_message:
        msgs.append(record.admin_message)
    result['resolution_message'] = '; '.join(msgs) if msgs else None
    
    return result


def get_fp_request_detail(request_id):
    """
    Get full details for a single FP request.
    
    Args:
        request_id: ID of the FP request
    
    Returns:
        Dict with request details or error
    """
    try:
        record = db.session.get(FalsePositiveRecord, request_id)
        if not record:
            return {'success': False, 'error': 'FP request not found'}
        
        result = _enrich_fp_record(record)
        return {'success': True, 'request': result}
    
    except Exception as e:
        logger.exception(f'Error getting FP request detail: {e}')
        return {'success': False, 'error': str(e)}


def get_fp_review_queue(user_id, role):
    """
    Get the review queue for an operator or admin.
    
    - Operator: PENDING_OPERATOR requests assigned to them
    - Admin: PENDING_ADMIN requests (all)
    
    Args:
        user_id: Current user's ID
        role: 'operator' or 'admin'
    
    Returns:
        Dict with queue items
    """
    try:
        if role == 'operator':
            records = FalsePositiveRecord.query.filter_by(
                status='PENDING_OPERATOR'
            ).order_by(FalsePositiveRecord.created_at.asc()).all()
        elif role == 'admin':
            records = FalsePositiveRecord.query.filter_by(
                status='PENDING_ADMIN'
            ).order_by(FalsePositiveRecord.created_at.asc()).all()
        else:
            return {'success': False, 'error': 'Invalid role. Must be operator or admin.'}
        
        return {
            'success': True,
            'queue': [_enrich_fp_record(r) for r in records],
            'count': len(records)
        }
    
    except Exception as e:
        logger.exception(f'Error getting review queue: {e}')
        return {'success': False, 'error': str(e), 'queue': [], 'count': 0}


# ============================================================
# SUPPRESSION ENFORCEMENT
# ============================================================

def get_suppressed_fingerprints():
    """
    Get the set of all currently suppressed fingerprints.
    
    Only APPROVED_FP fingerprints are considered suppressed.
    REVERTED_TO_TP ones are NOT suppressed.
    
    Returns:
        Set of fingerprint strings
    """
    try:
        records = FalsePositiveRecord.query.filter_by(status='APPROVED_FP').all()
        return {r.fingerprint for r in records}
    except Exception as e:
        logger.exception(f'Error getting suppressed fingerprints: {e}')
        return set()


def check_fingerprint_suppressed(fingerprint):
    """
    Check if a specific fingerprint is suppressed.
    
    Args:
        fingerprint: SHA256 fingerprint string
    
    Returns:
        Tuple of (is_suppressed: bool, record_id: int or None)
    """
    try:
        record = FalsePositiveRecord.query.filter_by(
            fingerprint=fingerprint,
            status='APPROVED_FP'
        ).first()
        if record:
            return True, record.id
        return False, None
    except Exception as e:
        logger.exception(f'Error checking fingerprint suppression: {e}')
        return False, None


def apply_suppressions_to_findings(findings):
    """
    Apply FP suppressions to a list of findings.
    
    For each finding, checks if its fingerprint is in the suppressed set.
    If so, adds 'suppressed': true to the finding dict.
    
    This is the key function called during scan result rendering.
    The finding is NEVER deleted - only marked as suppressed.
    
    Args:
        findings: List of finding dicts from merged.json
    
    Returns:
        The same list with 'suppressed' flags added
    """
    if not findings:
        return findings
    
    try:
        suppressed = get_suppressed_fingerprints()
        if not suppressed:
            return findings
        
        for finding in findings:
            fp = fp_fingerprint_from_finding(finding)
            if fp in suppressed:
                finding['suppressed'] = True
        
        return findings
    
    except Exception as e:
        logger.exception(f'Error applying suppressions: {e}')
        return findings
