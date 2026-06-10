# models/database.py
"""
SQLAlchemy database models for VIRTUAL_PLUMBER
- User management
- Session tracking
- Audit logging
- User preferences
- Scan history
"""

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import bcrypt
import secrets
import json

db = SQLAlchemy()


class User(db.Model):
    """User account model"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255))
    password_hash = db.Column(db.String(255), nullable=False)
    password_salt = db.Column(db.String(255), default='')  # For future use, bcrypt handles salt internally
    
    # First login & password management
    is_first_login = db.Column(db.Boolean, default=True)
    password_changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    password_history = db.Column(db.Text, default='[]')  # JSON array of old hashes
    
    # Account status
    account_status = db.Column(db.String(50), default='active')  # active, locked, disabled
    failed_login_attempts = db.Column(db.Integer, default=0)
    last_failed_login = db.Column(db.DateTime)
    locked_until = db.Column(db.DateTime)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Role
    role = db.Column(db.String(50), default='admin')  # admin, operator, viewer
    
    # GitHub Credentials (Encrypted)
    encrypted_github_app_id = db.Column(db.Text)  # Encrypted GitHub App ID
    encrypted_github_key = db.Column(db.Text)  # Encrypted GitHub Private Key
    github_credentials_updated_at = db.Column(db.DateTime)  # When credentials were last updated
    
    # PR Scan Settings
    pr_scan_enabled = db.Column(db.Boolean, default=True)  # Toggle for automatic PR scanning
    pr_block_enabled = db.Column(db.Boolean, default=False)  # Block PR on findings at or above threshold
    pr_block_severity = db.Column(db.String(20), default='HIGH')  # Min severity to block: CRITICAL, HIGH, MEDIUM, LOW
    
    # User Metadata (for User Management)
    full_name = db.Column(db.String(255))  # User's full name
    department = db.Column(db.String(255))  # Department/team
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Who created this user
    
    # Relationships
    creator = db.relationship('User', remote_side='User.id', backref=db.backref('created_users', lazy='dynamic'))
    preferences = db.relationship('UserPreferences', uselist=False, backref='user', 
                                 cascade='all, delete-orphan')
    sessions = db.relationship('Session', backref='user', cascade='all, delete-orphan')
    audit_logs = db.relationship('AuditLog', backref='user')
    scan_history = db.relationship('ScanHistory', backref='user', cascade='all, delete-orphan')
    
    @staticmethod
    def hash_password(password):
        """Hash password with bcrypt"""
        salt = bcrypt.gensalt(rounds=12)
        hash_obj = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hash_obj.decode('utf-8')
    
    def check_password(self, password):
        """Verify password against hash"""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
        except Exception:
            return False
    
    def is_locked(self):
        """Check if account is locked"""
        # Check if manually locked
        if self.locked_until and self.locked_until > datetime.utcnow():
            return True
        # Check if too many failed attempts
        if self.failed_login_attempts >= 5:
            return True
        return False
    
    def increment_failed_login(self):
        """Increment failed login counter and lock if necessary"""
        self.failed_login_attempts += 1
        self.last_failed_login = datetime.utcnow()
        
        if self.failed_login_attempts >= 5:
            self.locked_until = datetime.utcnow() + timedelta(minutes=15)
            self.account_status = 'locked'
        
        db.session.commit()
    
    def reset_failed_login(self):
        """Reset failed login counter on successful login"""
        self.failed_login_attempts = 0
        self.last_failed_login = None
        self.locked_until = None
        if self.account_status == 'locked':
            self.account_status = 'active'
        self.last_login = datetime.utcnow()
        db.session.commit()
    
    def add_to_password_history(self, password_hash):
        """Add password hash to history (keep last 5)"""
        try:
            history = json.loads(self.password_history) if self.password_history else []
        except json.JSONDecodeError:
            history = []
        
        history.insert(0, password_hash)
        # Keep only last 5
        history = history[:5]
        self.password_history = json.dumps(history)
    
    def password_in_history(self, password):
        """Check if password is in history"""
        try:
            history = json.loads(self.password_history) if self.password_history else []
        except json.JSONDecodeError:
            return False
        
        for old_hash in history:
            if bcrypt.checkpw(password.encode('utf-8'), old_hash.encode('utf-8')):
                return True
        return False
    
    def to_dict(self):
        """Serialize user to dictionary (safe, no password)"""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'is_first_login': self.is_first_login,
            'account_status': self.account_status,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'created_at': self.created_at.isoformat()
        }


class Session(db.Model):
    """User session model"""
    __tablename__ = 'sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    session_token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    session_hash = db.Column(db.String(255), nullable=False)
    
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow)
    
    @staticmethod
    def generate_session_token():
        """Generate cryptographically secure session token"""
        return secrets.token_urlsafe(32)
    
    def is_valid(self):
        """Check if session is still valid"""
        return self.expires_at > datetime.utcnow()
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'session_token': self.session_token,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat(),
            'is_valid': self.is_valid()
        }


class AuditLog(db.Model):
    """Audit logging model"""
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    username = db.Column(db.String(255))
    user_role = db.Column(db.String(50))
    action = db.Column(db.String(255), nullable=False, index=True)
    resource_type = db.Column(db.String(100))
    resource_id = db.Column(db.String(255))
    
    old_value = db.Column(db.Text)  # JSON
    new_value = db.Column(db.Text)  # JSON
    
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    
    status = db.Column(db.String(50), default='success')  # success, failure
    error_message = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.username,
            'user_role': self.user_role,
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'old_value': json.loads(self.old_value) if self.old_value else None,
            'new_value': json.loads(self.new_value) if self.new_value else None,
            'status': self.status,
            'error_message': self.error_message,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat()
        }


class UserPreferences(db.Model):
    """User preferences model"""
    __tablename__ = 'user_preferences'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, 
                       nullable=False, index=True)
    
    # UI State
    active_tab = db.Column(db.String(50), default='overview')
    theme = db.Column(db.String(20), default='light')  # light, dark, auto
    items_per_page = db.Column(db.Integer, default=20)
    
    # Scan Settings
    default_scan_types = db.Column(db.Text, default='["sats", "sbom", "secret"]')  # JSON
    auto_scan_enabled = db.Column(db.Boolean, default=False)
    auto_scan_interval = db.Column(db.Integer)  # minutes
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'active_tab': self.active_tab,
            'theme': self.theme,
            'items_per_page': self.items_per_page,
            'default_scan_types': json.loads(self.default_scan_types),
            'auto_scan_enabled': self.auto_scan_enabled,
            'auto_scan_interval': self.auto_scan_interval
        }


class ScanHistory(db.Model):
    """Scan history model (migrated from JSON files)"""
    __tablename__ = 'scan_history'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    
    scan_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    repo_id = db.Column(db.String(255))
    repo_name = db.Column(db.String(255))
    repo_owner = db.Column(db.String(255))
    repo_branch = db.Column(db.String(100))
    
    # PR Scan fields
    is_pr_scan = db.Column(db.Boolean, default=False, index=True)  # True if this is a PR scan
    pr_number = db.Column(db.Integer, nullable=True, index=True)  # PR number (e.g., 42)
    pr_title = db.Column(db.String(500), nullable=True)  # PR title
    pr_head_ref = db.Column(db.String(255), nullable=True)  # PR branch ref (e.g., refs/pull/42/head)
    
    scan_types = db.Column(db.Text)  # JSON: ["sats", "sbom", "secret"]
    scan_status = db.Column(db.String(50), default='running')  # running, completed, failed
    
    summary = db.Column(db.Text)  # JSON: {total_unique, by_severity, by_category}
    
    findings_file_path = db.Column(db.String(512))
    opengrep_file_path = db.Column(db.String(512))
    truffle_file_path = db.Column(db.String(512))
    trivy_file_path = db.Column(db.String(512))
    
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    duration_seconds = db.Column(db.Integer)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'scan_id': self.scan_id,
            'repo_name': self.repo_name,
            'repo_owner': self.repo_owner,
            'repo_branch': self.repo_branch,
            'scan_types': json.loads(self.scan_types) if self.scan_types else [],
            'scan_status': self.scan_status,
            'summary': json.loads(self.summary) if self.summary else {},
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration_seconds': self.duration_seconds,
            'created_at': self.created_at.isoformat(),
            # PR Scan fields
            'is_pr_scan': self.is_pr_scan,
            'pr_number': self.pr_number,
            'pr_title': self.pr_title,
            'pr_head_ref': self.pr_head_ref
        }
