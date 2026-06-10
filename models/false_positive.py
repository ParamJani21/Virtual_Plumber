from models.database import db
from datetime import datetime

class FalsePositiveRecord(db.Model):
    __tablename__ = 'false_positive_records'
    
    id = db.Column(db.Integer, primary_key=True)
    fingerprint = db.Column(db.Text, unique=True, nullable=False, index=True)
    
    # Scan context
    repo_name = db.Column(db.Text)
    branch_name = db.Column(db.Text)
    commit_hash = db.Column(db.Text)
    
    # Finding metadata
    tool_name = db.Column(db.Text)  # opengrep, trufflehog, trivy
    finding_type = db.Column(db.Text)  # private_key, sql_injection, secret, etc.
    severity = db.Column(db.Text)  # CRITICAL, MEDIUM, LOW
    cwe = db.Column(db.Text)  # comma-separated CWE list
    
    # Code location
    file_path = db.Column(db.Text)
    line_number = db.Column(db.Integer)
    matched_code = db.Column(db.Text)  # The raw code line that matched
    code_context = db.Column(db.Text)  # Surrounding code context (few lines before/after)
    
    # Scanner metadata
    scanner_message = db.Column(db.Text)
    remediation = db.Column(db.Text)
    
    # Workflow - who
    created_by_viewer_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    operator_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # assigned operator
    approved_by_operator_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_by_admin_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Relationships (so ORM can load related users)
    creator = db.relationship('User', foreign_keys=[created_by_viewer_id])
    operator_rel = db.relationship('User', foreign_keys=[operator_id])
    operator_approver = db.relationship('User', foreign_keys=[approved_by_operator_id])
    admin_approver = db.relationship('User', foreign_keys=[approved_by_admin_id])
    
    # Messages
    viewer_reason = db.Column(db.Text)  # Viewer's justification
    operator_message = db.Column(db.Text)  # Operator's review note
    admin_message = db.Column(db.Text)  # Admin's review note
    
    # Escalation history - JSON array of {from_role, to_role, timestamp, message}
    escalation_history = db.Column(db.Text)  
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_at = db.Column(db.DateTime)
    
    # Status lifecycle
    status = db.Column(db.Text, nullable=False, default='PENDING_OPERATOR', index=True)
    # Possible values:
    # PENDING_OPERATOR → waiting for operator review
    # OPERATOR_REJECTED → rejected by operator
    # PENDING_ADMIN → approved by operator, waiting for admin
    # ADMIN_REJECTED → rejected by admin
    # APPROVED_FP → fully approved, globally suppressed
    # REVERTED_TO_TP → was APPROVED_FP, now reverted back
    
    # Revert tracking
    reverted_to_tp = db.Column(db.Integer, default=0)
    reverted_at = db.Column(db.DateTime)
    
    def to_dict(self):
        """Serialize to dict for API responses"""
        return {
            'id': self.id,
            'fingerprint': self.fingerprint,
            'repo_name': self.repo_name,
            'branch_name': self.branch_name,
            'commit_hash': self.commit_hash,
            'tool_name': self.tool_name,
            'finding_type': self.finding_type,
            'severity': self.severity,
            'cwe': self.cwe,
            'file_path': self.file_path,
            'line_number': self.line_number,
            'matched_code': self.matched_code,
            'code_context': self.code_context,
            'scanner_message': self.scanner_message,
            'remediation': self.remediation,
            'created_by_viewer_id': self.created_by_viewer_id,
            'operator_id': self.operator_id,
            'approved_by_operator_id': self.approved_by_operator_id,
            'approved_by_admin_id': self.approved_by_admin_id,
            'viewer_reason': self.viewer_reason,
            'operator_message': self.operator_message,
            'admin_message': self.admin_message,
            'escalation_history': self.escalation_history,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'status': self.status,
            'reverted_to_tp': bool(self.reverted_to_tp),
            'reverted_at': self.reverted_at.isoformat() if self.reverted_at else None,
        }
