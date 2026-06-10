# validators/input_validators.py
"""
Input validation and sanitization functions
"""

import re
from urllib.parse import urlparse


def validate_username(username):
    """
    Validate username format
    
    Args:
        username: Username to validate
    
    Returns:
        Tuple of (is_valid: bool, error_message: str or None)
    """
    if not isinstance(username, str):
        return False, "Username must be string"
    
    username = username.strip()
    
    if len(username) < 4:
        return False, "Username must be at least 4 characters"
    
    if len(username) > 20:
        return False, "Username must not exceed 20 characters"
    
    # Only alphanumeric, underscore, hyphen
    if not re.match(r'^[a-zA-Z0-9_-]+$', username):
        return False, "Username can only contain letters, numbers, underscore, and hyphen"
    
    # Cannot start with numbers
    if username[0].isdigit():
        return False, "Username cannot start with a number"
    
    return True, None


def validate_email(email):
    """
    Validate email format
    
    Args:
        email: Email to validate
    
    Returns:
        Tuple of (is_valid: bool, error_message: str or None)
    """
    if not isinstance(email, str):
        return False, "Email must be string"
    
    email = email.strip()
    
    if len(email) < 5 or len(email) > 255:
        return False, "Email length invalid"
    
    # Basic email regex
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(pattern, email):
        return False, "Invalid email format"
    
    return True, None


def validate_password(password):
    """
    Validate password field format (basic check)
    
    Args:
        password: Password to validate
    
    Returns:
        Tuple of (is_valid: bool, error_message: str or None)
    """
    if not isinstance(password, str):
        return False, "Password must be string"
    
    if len(password) < 1:
        return False, "Password cannot be empty"
    
    if len(password) > 512:
        return False, "Password is too long"
    
    return True, None


def validate_password_strength(password, username=None, old_passwords=None):
    """
    Validate password strength requirements
    
    Requirements:
    - Minimum 12 characters
    - At least 1 UPPERCASE letter
    - At least 1 lowercase letter
    - At least 1 number
    - At least 1 special character (!@#$%^&*)
    - NOT username
    - NOT in password history
    
    Args:
        password: Password to validate
        username: Username to check against (optional)
        old_passwords: List of old password hashes to check against (optional)
    
    Returns:
        Tuple of (is_valid: bool, error_message: str or None)
    """
    import bcrypt
    
    if not isinstance(password, str):
        return False, "Password must be string"
    
    errors = []
    
    # Length
    if len(password) < 12:
        errors.append("Password must be at least 12 characters")
    
    if len(password) > 128:
        errors.append("Password is too long (max 128 characters)")
    
    # Uppercase
    if not any(c.isupper() for c in password):
        errors.append("Password must contain at least one UPPERCASE letter")
    
    # Lowercase
    if not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter")
    
    # Numbers
    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one number")
    
    # Special chars
    if not any(c in '!@#$%^&*' for c in password):
        errors.append("Password must contain at least one special character (!@#$%^&*)")
    
    # Not username
    if username and username.lower() in password.lower():
        errors.append("Password cannot contain username")
    
    # Not in history
    if old_passwords:
        for old_hash in old_passwords:
            try:
                if isinstance(old_hash, str) and bcrypt.checkpw(password.encode('utf-8'), old_hash.encode('utf-8')):
                    errors.append("Password cannot be same as last 5 passwords used")
                    break
            except Exception:
                # Skip invalid hashes in history
                pass
    
    if errors:
        return False, " | ".join(errors)
    
    return True, None


def validate_repo_name(repo_name):
    """
    Validate GitHub repository name
    
    Args:
        repo_name: Repository name to validate
    
    Returns:
        Tuple of (is_valid: bool, error_message: str or None)
    """
    if not isinstance(repo_name, str):
        return False, "Repository name must be string"
    
    repo_name = repo_name.strip()
    
    if len(repo_name) < 1:
        return False, "Repository name cannot be empty"
    
    if len(repo_name) > 100:
        return False, "Repository name is too long (max 100 characters)"
    
    # GitHub allows alphanumeric, hyphen, underscore, dot, slash
    if not re.match(r'^[a-zA-Z0-9._/-]+$', repo_name):
        return False, "Invalid repository name format"
    
    return True, None


def validate_branch_name(branch_name):
    """
    Validate Git branch name
    
    Args:
        branch_name: Branch name to validate
    
    Returns:
        Tuple of (is_valid: bool, error_message: str or None)
    """
    if not isinstance(branch_name, str):
        return False, "Branch name must be string"
    
    branch_name = branch_name.strip()
    
    if len(branch_name) < 1:
        return False, "Branch name cannot be empty"
    
    if len(branch_name) > 255:
        return False, "Branch name is too long (max 255 characters)"
    
    # Restrictive: alphanumeric, dot, slash, hyphen, underscore
    if not re.match(r'^[a-zA-Z0-9._\/-]+$', branch_name):
        return False, "Invalid branch name format"
    
    # No spaces, no special chars like @, :, etc.
    if any(c in '@:[]' for c in branch_name):
        return False, "Branch name contains invalid characters"
    
    return True, None


def validate_scan_id(scan_id):
    """
    Validate scan ID format (UUID format)
    Prevents path traversal attacks
    
    Args:
        scan_id: Scan ID to validate
    
    Returns:
        Tuple of (is_valid: bool, error_message: str or None)
    """
    if not isinstance(scan_id, str):
        return False, "Scan ID must be string"
    
    # UUID format: 8-4-4-4-12 hex digits
    # Pattern: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    
    if not re.match(uuid_pattern, scan_id, re.IGNORECASE):
        return False, "Invalid scan ID format (must be valid UUID)"
    
    # Additional check: no path traversal attempts
    if '..' in scan_id or '/' in scan_id or '\\' in scan_id:
        return False, "Invalid scan ID (potential path traversal)"
    
    return True, None


def sanitize_json_input(data, allowed_keys, max_size_bytes=10000):
    """
    Sanitize and validate JSON input
    
    Args:
        data: Dictionary to sanitize
        allowed_keys: List of allowed keys
        max_size_bytes: Maximum size of data
    
    Returns:
        Tuple of (sanitized_dict: dict or None, error_message: str or None)
    """
    import sys
    
    if not isinstance(data, dict):
        return None, "Input must be JSON object"
    
    # Check size
    if sys.getsizeof(data) > max_size_bytes:
        return None, "Input data is too large"
    
    # Check keys
    sanitized = {}
    for key in allowed_keys:
        if key in data:
            value = data[key]
            # Don't include None values
            if value is not None:
                sanitized[key] = value
    
    return sanitized, None


def sanitize_string(text, max_length=1000, allow_newlines=False):
    """
    Sanitize string input
    
    Args:
        text: Text to sanitize
        max_length: Maximum allowed length
        allow_newlines: Whether to allow newline characters
    
    Returns:
        Sanitized string
    """
    if not isinstance(text, str):
        return ""
    
    # Strip whitespace
    text = text.strip()
    
    # Remove control characters
    text = ''.join(c for c in text if ord(c) >= 32 or c in '\n\r\t')
    
    # Remove newlines if not allowed
    if not allow_newlines:
        text = text.replace('\n', '').replace('\r', '')
    
    # Truncate to max length
    if len(text) > max_length:
        text = text[:max_length]
    
    return text
