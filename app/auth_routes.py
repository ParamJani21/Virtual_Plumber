# app/auth_routes.py
"""
Authentication routes for VIRTUAL_PLUMBER
- Login
- Logout
- Change Password
- Initial Admin Setup
"""

from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.database import db, User, UserPreferences
from validators.input_validators import (
    validate_username, validate_password, validate_password_strength, validate_email
)
from auth.utils import (
    log_audit_event, log_failed_login, create_session_record, destroy_session
)
from auth.decorators import require_login, require_admin
from flask import current_app

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/login', methods=['GET'])
def login_page():
    """Display login page"""
    if 'user_id' in session:
        return redirect('/dashboard')
    
    error = request.args.get('error')
    info = request.args.get('info')
    return render_template('login.html', error=error, info=info)


@auth_bp.route('/login', methods=['POST'])
def login():
    """Process login"""
    try:
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
            username = data.get('username', '').strip()
            password = data.get('password', '')
        else:
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
        
        # Validate input
        if not username or not password:
            if request.is_json:
                return jsonify({'error': 'Missing username or password'}), 400
            else:
                return render_template('login.html', error='Missing username or password'), 400
        
        # Validate username format
        is_valid, error_msg = validate_username(username)
        if not is_valid:
            log_failed_login(username, request.remote_addr)
            if request.is_json:
                return jsonify({'error': 'Invalid username format'}), 400
            else:
                return render_template('login.html', error='Invalid username format'), 400
        
        # Get user from database
        user = User.query.filter_by(username=username).first()
        
        if not user:
            log_failed_login(username, request.remote_addr)
            if request.is_json:
                return jsonify({'error': 'Invalid credentials'}), 401
            else:
                return render_template('login.html', error='Invalid credentials'), 401
        
        # Check if account is locked
        if user.is_locked():
            log_failed_login(username, request.remote_addr)
            if request.is_json:
                return jsonify({'error': 'Account is locked. Try again later'}), 403
            else:
                return render_template('login.html', error='Account is locked. Try again later'), 403
        
        # Verify password
        if not user.check_password(password):
            user.increment_failed_login()
            log_failed_login(username, request.remote_addr)
            if request.is_json:
                return jsonify({'error': 'Invalid credentials'}), 401
            else:
                return render_template('login.html', error='Invalid credentials'), 401
        
        # Success - reset failed attempts
        user.reset_failed_login()
        
        # Create session
        session.permanent = True
        current_app.permanent_session_lifetime = timedelta(hours=8)
        session['user_id'] = user.id
        session['username'] = user.username
        
        # Create session record in database
        session_record = create_session_record(
            user_id=user.id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')
        )
        
        if session_record:
            session['session_token'] = session_record.session_token
        
        # Log successful login
        log_audit_event(
            user_id=user.id,
            action='LOGIN_SUCCESS',
            resource_type='authentication'
        )
        
        # Prepare response
        response_data = {
            'status': 'success',
            'first_login': user.is_first_login,
            'redirect': '/change-password?first_login=true' if user.is_first_login else '/dashboard'
        }
        
        if request.is_json:
            return jsonify(response_data), 200
        else:
            if user.is_first_login:
                return redirect('/auth/change-password?first_login=true')
            else:
                return redirect('/dashboard')
    
    except Exception as e:
        current_app.logger.error(f'Login error: {str(e)}')
        if request.is_json:
            return jsonify({'error': 'An error occurred during login'}), 500
        else:
            return render_template('login.html', error='An error occurred during login'), 500


@auth_bp.route('/logout', methods=['GET', 'POST'])
@require_login
def logout():
    """Logout user"""
    try:
        user_id = session.get('user_id')
        
        # Log logout event
        log_audit_event(
            user_id=user_id,
            action='LOGOUT',
            resource_type='authentication'
        )
        
        # Destroy all sessions for this user
        destroy_session(user_id)
        
        # Clear session
        session.clear()
        
        if request.is_json:
            return jsonify({'status': 'logged_out'}), 200
        else:
            return redirect('/login?info=You+have+been+logged+out')
    
    except Exception as e:
        current_app.logger.error(f'Logout error: {str(e)}')
        session.clear()
        if request.is_json:
            return jsonify({'error': 'Logout failed'}), 500
        else:
            return redirect('/login')


@auth_bp.route('/change-password', methods=['GET'])
@require_login
def change_password_page():
    """Display change password page"""
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    if not user:
        session.clear()
        return redirect('/login')
    
    # Use database value, NOT URL parameter (security: prevent client-side manipulation)
    first_login = user.is_first_login
    
    return render_template('change_password.html', 
                         first_login=first_login,
                         username=user.username)


@auth_bp.route('/change-password', methods=['POST'])
@require_login
def change_password():
    """Process password change"""
    try:
        user_id = session.get('user_id')
        user = User.query.get(user_id)
        
        if not user:
            session.clear()
            return jsonify({'error': 'User not found'}), 401
        
        # Get form data
        current_password = request.form.get('current_password', '').strip()
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        first_login = user.is_first_login
        
        # Validate input
        if not new_password or not confirm_password:
            return jsonify({'error': 'Missing password fields'}), 400
        
        # Require current password if not first login
        if not first_login and not current_password:
            return jsonify({'error': 'Current password is required'}), 400
        
        # Verify current password if not first login
        if not first_login:
            if not user.check_password(current_password):
                log_audit_event(
                    user_id=user_id,
                    action='PASSWORD_CHANGE_FAILED',
                    resource_type='authentication',
                    status='failure',
                    error_message='Invalid current password'
                )
                return jsonify({'error': 'Current password is incorrect'}), 401
        
        # Validate passwords match
        if new_password != confirm_password:
            return jsonify({'error': 'Passwords do not match'}), 400
        
        # Validate password strength
        try:
            password_history = []
            if user.password_history:
                import json
                password_history = json.loads(user.password_history)
        except:
            password_history = []
        
        is_valid, error_msg = validate_password_strength(
            new_password,
            username=user.username,
            old_passwords=password_history
        )
        
        if not is_valid:
            return jsonify({'error': error_msg}), 400
        
        # Update password
        old_hash = user.password_hash
        user.add_to_password_history(old_hash)
        user.password_hash = User.hash_password(new_password)
        user.password_changed_at = datetime.utcnow()
        user.is_first_login = False
        
        db.session.commit()
        
        # Log password change
        log_audit_event(
            user_id=user_id,
            action='PASSWORD_CHANGED',
            resource_type='authentication',
            status='success'
        )
        
        response_data = {
            'status': 'success',
            'message': 'Password changed successfully',
            'redirect': '/dashboard'
        }
        
        return jsonify(response_data), 200
    
    except Exception as e:
        current_app.logger.error(f'Password change error: {str(e)}')
        return jsonify({'error': 'An error occurred during password change'}), 500


@auth_bp.route('/setup/initial-admin', methods=['POST'])
def setup_initial_admin():
    """
    Create initial admin account
    Only works if no admin exists
    Disabled after first admin is created
    """
    try:
        # Check if admin already exists
        admin_exists = User.query.filter_by(role='admin').first()
        if admin_exists:
            return jsonify({
                'error': 'Admin account already exists',
                'code': 'ADMIN_EXISTS'
            }), 403
        
        # Get form data
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        
        # Validate username
        is_valid, error_msg = validate_username(username)
        if not is_valid:
            return jsonify({'error': error_msg}), 400
        
        # Check if username already exists
        user_exists = User.query.filter_by(username=username).first()
        if user_exists:
            return jsonify({'error': 'Username already exists'}), 400
        
        # Validate email if provided
        if email:
            is_valid, error_msg = validate_email(email)
            if not is_valid:
                return jsonify({'error': error_msg}), 400
        
        # Generate temporary password
        import secrets
        import string
        temp_password = ''.join(
            secrets.choice(string.ascii_letters + string.digits + '!@#$%^&*')
            for _ in range(16)
        )
        
        # Create user
        user = User(
            username=username,
            email=email or None,
            password_hash=User.hash_password(temp_password),
            is_first_login=True,
            account_status='active',
            role='admin'
        )
        
        db.session.add(user)
        db.session.commit()
        
        # Create default preferences
        preferences = UserPreferences(user_id=user.id)
        db.session.add(preferences)
        db.session.commit()
        
        # Log setup
        log_audit_event(
            user_id=user.id,
            action='ADMIN_SETUP',
            resource_type='user',
            resource_id=username,
            status='success'
        )
        
        return jsonify({
            'status': 'success',
            'message': 'Admin account created successfully',
            'username': username,
            'temporary_password': temp_password,
            'instructions': 'Use the temporary password to login. You will be required to change it on first login.'
        }), 201
    
    except Exception as e:
        current_app.logger.error(f'Admin setup error: {str(e)}')
        return jsonify({'error': 'An error occurred during admin setup'}), 500


@auth_bp.route('/status', methods=['GET'])
@require_login
def auth_status():
    """Get current authentication status"""
    try:
        user = User.query.get(session.get('user_id'))
        
        if not user:
            return jsonify({'authenticated': False, 'error': 'User not found'}), 401
        
        return jsonify({
            'authenticated': True,
            'user': user.to_dict(),
            'session_expires_at': (datetime.utcnow() + timedelta(hours=8)).isoformat()
        }), 200
    
    except Exception as e:
        current_app.logger.error(f'Auth status error: {str(e)}')
        return jsonify({'authenticated': False, 'error': 'Auth check failed'}), 500
