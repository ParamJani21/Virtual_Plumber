# auth/utils.py
"""
Authentication utilities for logging, session management, etc.
"""

from flask import request, session
from datetime import datetime, timedelta
from models.database import db, AuditLog, Session, User
import json
import logging

logger = logging.getLogger(__name__)


def log_audit_event(user_id=None, action=None, resource_type=None, 
                   resource_id=None, old_value=None, new_value=None, 
                   status='success', error_message=None,
                   username=None, user_role=None):
    """
    Log audit event to database
    
    Args:
        user_id: User performing the action (if None, uses session)
        action: Action name (e.g., 'LOGIN_SUCCESS', 'SCAN_TRIGGERED')
        resource_type: Type of resource affected (e.g., 'repository', 'scan')
        resource_id: ID of resource affected
        old_value: Previous value (dict/list)
        new_value: New value (dict/list)
        status: 'success' or 'failure'
        error_message: Error details if status is 'failure'
        username: Username (auto-resolved if None)
        user_role: User role (auto-resolved if None)
    
    Returns:
        AuditLog object
    """
    try:
        # Get user_id from session if not provided
        if user_id is None and 'user_id' in session:
            user_id = session.get('user_id')
        
        # Resolve username and role if not provided
        if (username is None or user_role is None) and user_id:
            user = User.query.get(user_id)
            if user:
                username = username or user.username
                user_role = user_role or user.role
        
        # Serialize old/new values to JSON
        old_val_json = json.dumps(old_value) if old_value else None
        new_val_json = json.dumps(new_value) if new_value else None
        
        audit_log = AuditLog(
            user_id=user_id,
            username=username,
            user_role=user_role,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            old_value=old_val_json,
            new_value=new_val_json,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:255],
            status=status,
            error_message=str(error_message)[:500] if error_message else None,
            created_at=datetime.utcnow()
        )
        
        db.session.add(audit_log)
        db.session.commit()
        
        logger.debug(f"Audit: {action} by {username or user_id} - {status}")
        
        return audit_log
    
    except Exception as e:
        logger.error(f"Failed to log audit event: {str(e)}")
        return None


def log_failed_login(username, ip_address=None):
    """
    Log failed login attempt
    
    Args:
        username: Username that failed to authenticate
        ip_address: IP address of attacker (if None, uses request.remote_addr)
    """
    if ip_address is None:
        ip_address = request.remote_addr
    
    try:
        audit_log = AuditLog(
            user_id=None,
            username=username,
            action='LOGIN_FAILED',
            resource_type='authentication',
            resource_id=username,
            ip_address=ip_address,
            user_agent=request.headers.get('User-Agent', '')[:255],
            status='failure',
            error_message='Invalid credentials',
            created_at=datetime.utcnow()
        )
        db.session.add(audit_log)
        db.session.commit()
        
        logger.warning(f"Failed login for {username} from {ip_address}")
    
    except Exception as e:
        logger.error(f"Failed to log failed login: {str(e)}")


def get_audit_logs(user_id=None, action=None, days=30, limit=100, offset=0, since=None, since_id=None):
    """
    Retrieve audit logs
    
    Args:
        user_id: Filter by specific user (None = all users)
        action: Filter by action type (None = all actions)
        days: Only logs from last N days (0 = all)
        limit: Maximum number of logs to return
        offset: Pagination offset
        since: ISO timestamp string - return only logs newer than this
        since_id: Return only logs with ID greater than this (more reliable than timestamps)
    
    Returns:
        List of AuditLog objects
    """
    try:
        query = AuditLog.query
        
        if user_id:
            query = query.filter_by(user_id=user_id)
        
        if action:
            query = query.filter_by(action=action)
        
        # Last N days
        if days > 0:
            since_dt = datetime.utcnow() - timedelta(days=days)
            query = query.filter(AuditLog.created_at >= since_dt)
        
        # Since ID (more reliable for incremental polling)
        if since_id:
            query = query.filter(AuditLog.id > since_id)
        
        # Since timestamp (fallback for incremental polling)
        if since and not since_id:
            try:
                since_dt = datetime.fromisoformat(since)
                query = query.filter(AuditLog.created_at >= since_dt)
            except ValueError:
                pass
        
        # Order by newest first
        query = query.order_by(AuditLog.created_at.desc())
        
        # Pagination
        total = query.count()
        logs = query.limit(limit).offset(offset).all()
        
        return {
            'total': total,
            'limit': limit,
            'offset': offset,
            'logs': [log.to_dict() for log in logs]
        }
    
    except Exception as e:
        logger.error(f"Failed to retrieve audit logs: {str(e)}")
        return {'total': 0, 'limit': limit, 'offset': offset, 'logs': []}


def create_session_record(user_id, ip_address=None, user_agent=None, 
                         duration_hours=8):
    """
    Create a new session record in the database
    
    Args:
        user_id: User ID for the session
        ip_address: Client IP address
        user_agent: Client user agent
        duration_hours: Session duration in hours
    
    Returns:
        Session object with generated token
    """
    try:
        session_token = Session.generate_session_token()
        
        session_record = Session(
            user_id=user_id,
            session_token=session_token,
            session_hash=session_token,  # In production, hash this
            ip_address=ip_address or request.remote_addr,
            user_agent=(user_agent or request.headers.get('User-Agent', ''))[:255],
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=duration_hours),
            last_activity=datetime.utcnow()
        )
        
        db.session.add(session_record)
        db.session.commit()
        
        logger.debug(f"Session created for user {user_id}")
        
        return session_record
    
    except Exception as e:
        logger.error(f"Failed to create session record: {str(e)}")
        return None


def validate_session(session_token, user_id=None):
    """
    Validate session token against database
    
    Args:
        session_token: Token to validate
        user_id: Expected user ID (optional, for additional validation)
    
    Returns:
        Tuple of (is_valid: bool, user_id: int or None, error_message: str)
    """
    try:
        if not session_token:
            return False, None, "No session token provided"
        
        session_record = Session.query.filter_by(session_token=session_token).first()
        
        if not session_record:
            return False, None, "Session not found"
        
        if not session_record.is_valid():
            # Delete expired session
            db.session.delete(session_record)
            db.session.commit()
            return False, None, "Session expired"
        
        # Check user_id if provided
        if user_id and session_record.user_id != user_id:
            return False, None, "User ID mismatch"
        
        # Check user still exists and is active
        user = User.query.get(session_record.user_id)
        if not user or user.account_status == 'disabled':
            return False, None, "User not found or disabled"
        
        # Update last activity
        session_record.last_activity = datetime.utcnow()
        db.session.commit()
        
        return True, session_record.user_id, None
    
    except Exception as e:
        logger.error(f"Session validation failed: {str(e)}")
        return False, None, str(e)


def get_audit_log_users(days=30):
    """
    Get list of users who have audit log entries, with counts.
    
    Args:
        days: Only consider logs from last N days (0 = all time)
    
    Returns:
        List of dicts with user info and log stats
    """
    try:
        query = db.session.query(
            AuditLog.user_id,
            db.func.coalesce(AuditLog.username, 'System').label('username'),
            db.func.coalesce(AuditLog.user_role, 'system').label('user_role'),
            db.func.count(AuditLog.id).label('log_count'),
            db.func.max(AuditLog.created_at).label('last_activity')
        )
        
        query = query.filter(AuditLog.user_id.isnot(None))
        
        if days > 0:
            since_dt = datetime.utcnow() - timedelta(days=days)
            query = query.filter(AuditLog.created_at >= since_dt)
        
        query = query.group_by(AuditLog.user_id)
        query = query.order_by(db.func.max(AuditLog.created_at).desc())
        
        users = []
        for row in query.all():
            users.append({
                'user_id': row.user_id,
                'username': row.username,
                'user_role': row.user_role,
                'log_count': row.log_count,
                'last_activity': row.last_activity.isoformat() if row.last_activity else None
            })
        
        return {'users': users, 'total': len(users)}
    
    except Exception as e:
        logger.error(f"Failed to get audit log users: {str(e)}")
        return {'users': [], 'total': 0}


def get_current_user():
    """
    Get current logged-in user from session
    
    Returns:
        User object or None
    """
    if 'user_id' not in session:
        return None
    
    try:
        user = User.query.get(session['user_id'])
        return user if user and user.account_status != 'disabled' else None
    except Exception:
        return None


def destroy_session(user_id=None):
    """
    Destroy all sessions for a user (logout)
    
    Args:
        user_id: User ID to logout (if None, uses current session)
    """
    try:
        if user_id is None and 'user_id' in session:
            user_id = session['user_id']
        
        if user_id:
            # Delete all sessions for this user
            Session.query.filter_by(user_id=user_id).delete()
            db.session.commit()
            
            logger.debug(f"All sessions destroyed for user {user_id}")
    
    except Exception as e:
        logger.error(f"Failed to destroy sessions: {str(e)}")
