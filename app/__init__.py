from flask import Flask, request, jsonify, redirect, url_for, session
import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import timedelta, datetime
import secrets

# Import database and session configuration
from models.database import db

# Import models so SQLAlchemy creates tables
from models.false_positive import FalsePositiveRecord
from flask_session import Session as FlaskSession


def create_app():
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    
    # Generate or load SECRET_KEY from environment or .env file (persistent)
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY')
    if not SECRET_KEY:
        from modules.env_config import env_config
        SECRET_KEY = env_config.get_setting('FLASK_SECRET_KEY')
    if not SECRET_KEY:
        SECRET_KEY = secrets.token_hex(32)
        env_config.save_setting('FLASK_SECRET_KEY', SECRET_KEY)
        os.environ['FLASK_SECRET_KEY'] = SECRET_KEY
    
    app.config['SECRET_KEY'] = SECRET_KEY
    
    # Database configuration
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'virtual_plumber.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Session configuration - filesystem using native WSL tmpfs (not Windows drive, avoids atomic-rename race conditions)
    session_dir = '/tmp/cicdsec_sessions'
    os.makedirs(session_dir, exist_ok=True)
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_FILE_DIR'] = session_dir
    app.config['SESSION_FILE_THRESHOLD'] = 500
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
    app.config['SESSION_COOKIE_NAME'] = 'cicdsec_session'
    app.config['SESSION_REFRESH_EACH_REQUEST'] = True
    
    # Initialize database
    db.init_app(app)
    
    # Initialize session
    FlaskSession(app)
    
    # Create database tables if they don't exist
    with app.app_context():
        try:
            db.create_all()
            
            # Add missing columns to existing tables (for database migrations)
            from sqlalchemy import text
            try:
                # Check if columns exist, if not add them
                result = db.session.execute(text("PRAGMA table_info(users)"))
                columns = [row[1] for row in result.fetchall()]
                
                if 'encrypted_github_app_id' not in columns:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN encrypted_github_app_id TEXT"))
                    app.logger.info('Added column: encrypted_github_app_id')
                if 'encrypted_github_key' not in columns:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN encrypted_github_key TEXT"))
                    app.logger.info('Added column: encrypted_github_key')
                if 'github_credentials_updated_at' not in columns:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN github_credentials_updated_at TIMESTAMP"))
                    app.logger.info('Added column: github_credentials_updated_at')
                if 'full_name' not in columns:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN full_name VARCHAR(255)"))
                    app.logger.info('Added column: full_name')
                if 'department' not in columns:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN department VARCHAR(255)"))
                    app.logger.info('Added column: department')
                if 'pr_scan_enabled' not in columns:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN pr_scan_enabled BOOLEAN DEFAULT 1"))
                    app.logger.info('Added column: pr_scan_enabled')
                if 'pr_block_enabled' not in columns:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN pr_block_enabled BOOLEAN DEFAULT 0"))
                    app.logger.info('Added column: pr_block_enabled')
                if 'pr_block_severity' not in columns:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN pr_block_severity VARCHAR(20) DEFAULT 'HIGH'"))
                    app.logger.info('Added column: pr_block_severity')
                if 'created_by_id' not in columns:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN created_by_id INTEGER REFERENCES users(id)"))
                    app.logger.info('Added column: created_by_id')
                
                # Audit log migration
                audit_cols = db.session.execute(text("PRAGMA table_info(audit_logs)"))
                audit_columns = [row[1] for row in audit_cols.fetchall()]
                if 'username' not in audit_columns:
                    db.session.execute(text("ALTER TABLE audit_logs ADD COLUMN username VARCHAR(255)"))
                    app.logger.info('Added column: audit_logs.username')
                if 'user_role' not in audit_columns:
                    db.session.execute(text("ALTER TABLE audit_logs ADD COLUMN user_role VARCHAR(50)"))
                    app.logger.info('Added column: audit_logs.user_role')
                
                db.session.commit()

                # Backfill old audit logs with NULL username/user_role
                try:
                    from models.database import User as UserModel
                    null_logs = db.session.execute(
                        text("SELECT id, user_id FROM audit_logs WHERE username IS NULL AND user_id IS NOT NULL")
                    ).fetchall()
                    backfilled = 0
                    for log_id, uid in null_logs:
                        user = db.session.get(UserModel, uid)
                        if user:
                            db.session.execute(
                                text("UPDATE audit_logs SET username = :u, user_role = :r WHERE id = :id"),
                                {"u": user.username, "r": user.role, "id": log_id}
                            )
                            backfilled += 1
                    if backfilled:
                        db.session.commit()
                        app.logger.info(f'Backfilled {backfilled} audit logs with username/role')
                except Exception as backfill_e:
                    app.logger.warning(f'Audit log backfill note: {backfill_e}')

                # False Positive Records migration
                fp_cols = db.session.execute(text("PRAGMA table_info(false_positive_records)"))
                fp_columns = [row[1] for row in fp_cols.fetchall()]
                if fp_columns:
                    if 'updated_at' not in fp_columns:
                        db.session.execute(text("ALTER TABLE false_positive_records ADD COLUMN updated_at TIMESTAMP"))
                        app.logger.info('Added column: false_positive_records.updated_at')
                else:
                    app.logger.info('FalsePositiveRecord table will be created by SQLAlchemy')

            except Exception as col_e:
                app.logger.warning(f'Column migration note: {col_e}')

            # Create default admin if no admin exists
            from models.database import User, UserPreferences
            admin_exists = User.query.filter_by(role='admin').first()
            if not admin_exists:
                try:
                    app.logger.info('Creating default admin account...')
                    password_hash = User.hash_password('Securepass123@#')
                    app.logger.info(f'Password hash generated: {password_hash[:20]}...')

                    default_admin = User(
                        username='admin',
                        password_hash=password_hash,
                        is_first_login=True,
                        account_status='active',
                        role='admin'
                    )
                    db.session.add(default_admin)
                    db.session.flush()

                    prefs = UserPreferences(user_id=default_admin.id)
                    db.session.add(prefs)
                    db.session.commit()
                    app.logger.info('✓ Default admin created: admin / Securepass123@#')
                except Exception as admin_e:
                    app.logger.error(f'✗ Failed to create default admin: {str(admin_e)}')
                    import traceback
                    traceback.print_exc()

            # Startup cleanup: mark stale in-progress scans as failed
            try:
                from models.database import ScanHistory
                stale_scans = ScanHistory.query.filter(
                    ScanHistory.scan_status.in_(['running', 'in_progress', 'pending'])
                ).all()
                for scan in stale_scans:
                    app.logger.warning(f'[Startup] Marking stale scan as failed: {scan.scan_id}')
                    scan.scan_status = 'failed'
                    if not scan.completed_at:
                        scan.completed_at = datetime.utcnow()
                if stale_scans:
                    db.session.commit()
                    app.logger.info(f'[Startup] ✓ Marked {len(stale_scans)} stale scan(s) as failed')
            except Exception as stale_e:
                app.logger.warning(f'[Startup] Stale scan cleanup note: {stale_e}')

            # Startup cleanup: remove leftover cloned repos from /tmp/
            try:
                tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tmp')
                if os.path.exists(tmp_dir):
                    import shutil
                    for entry in os.listdir(tmp_dir):
                        entry_path = os.path.join(tmp_dir, entry)
                        if os.path.isdir(entry_path):
                            try:
                                shutil.rmtree(entry_path)
                                app.logger.info(f'[Startup] ✓ Removed stale clone: {entry}')
                            except Exception as rm_e:
                                app.logger.warning(f'[Startup] Could not remove {entry}: {rm_e}')
            except Exception as tmp_e:
                app.logger.warning(f'[Startup] Tmp cleanup note: {tmp_e}')

            # Startup cleanup: warn about stale PR scans (manual GitHub status fix needed)
            try:
                from models.database import ScanHistory
                stale_pr_count = ScanHistory.query.filter(
                    ScanHistory.is_pr_scan == True,
                    ScanHistory.scan_status.in_(['failed', 'running', 'in_progress', 'pending'])
                ).count()
                if stale_pr_count > 0:
                    app.logger.warning(f'[Startup] {stale_pr_count} stale PR scan(s) found. '
                                       f'GitHub commit status may still show "pending". '
                                       f'Re-run the scan or manually update the commit status.')
            except Exception as stale_gh_e:
                app.logger.debug(f'[Startup] Stale PR scan check note: {stale_gh_e}')

            app.logger.info('Database initialized successfully')
        except Exception as e:
            app.logger.error(f'Failed to initialize database: {e}')
    # Configure logging: console + rotating file
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, 'app.log')

    formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')

    # Clear all existing handlers on root logger to prevent duplication on re-init
    root_logger = logging.getLogger()
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    # File handler
    file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Add handlers only to root logger; app.logger and all module loggers
    # propagate to root by default, so they inherit these handlers automatically.
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Set levels on specific loggers (no handlers — they inherit from root)
    app.logger.setLevel(logging.INFO)
    logging.getLogger('werkzeug').setLevel(logging.INFO)
    logging.getLogger('werkzeug.serving').setLevel(logging.WARNING)
    logging.getLogger('werkzeug.security').setLevel(logging.WARNING)
    logging.getLogger('watchdog').setLevel(logging.ERROR)
    logging.getLogger('watchdog.observers').setLevel(logging.ERROR)
    logging.getLogger('watchdog.observers.inotify_buffer').setLevel(logging.ERROR)

    from app.routes import bp
    app.register_blueprint(bp)
    
    # Register authentication blueprint
    from app.auth_routes import auth_bp
    app.register_blueprint(auth_bp)

    # Register scan API blueprint (controls for cloning/scanning)
    try:
        from modules.scan_api import bp as scan_bp
        app.register_blueprint(scan_bp)
    except Exception as e:
        app.logger.warning('Could not register scan_api blueprint: %s', e)

    # Register false positive management blueprint
    try:
        from app.fp_routes import fp_bp
        app.register_blueprint(fp_bp)
    except Exception as e:
        app.logger.warning('Could not register fp_routes blueprint: %s', e)

    # Before request - check authentication (skip for auth routes and static files)
    @app.before_request
    def check_authentication():
        """Check if user is authenticated before accessing protected routes"""
        # Skip for static files, auth routes, login page, and GitHub webhooks
        if (request.path.startswith('/static/') or 
            request.path.startswith('/auth/') or 
            request.path.startswith('/github/') or
            request.path in ['/login', '/', '/auth/setup/initial-admin']):
            return
        
        # Check if user is logged in
        if 'user_id' not in session:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            else:
                return redirect(url_for('auth.login_page'))

    # Add security headers
    @app.after_request
    def set_security_headers(response):
        """Set security headers on all responses"""
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        return response

    # CSRF protection via Origin/Referer check
    @app.before_request
    def csrf_protect():
        if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
            return
        if not request.path.startswith('/api/'):
            return
        if request.path.startswith('/github/webhook'):
            return
        origin = request.headers.get('Origin')
        referer = request.headers.get('Referer')
        if origin is None and referer is None:
            return
        allowed = request.host_url.rstrip('/')
        if origin and not origin.startswith(allowed):
            return jsonify({'error': 'CSRF validation failed'}), 403
        if referer and not referer.startswith(allowed):
            return jsonify({'error': 'CSRF validation failed'}), 403

    # Log incoming requests (method, path, remote addr, params/body)
    @app.before_request
    def log_request_info():
        try:
            data = None
            try:
                data = request.get_json(silent=True)
            except Exception:
                data = None
            app.logger.debug('Incoming request: %s %s from %s params=%s json=%s',
                             request.method, request.path, request.remote_addr, dict(request.args), data)
        except Exception as e:
            app.logger.exception('Error logging request info: %s', e)

    # Context processor: expose current user role to all templates
    @app.context_processor
    def inject_user_role():
        from auth.utils import get_current_user
        user = get_current_user()
        return dict(current_user_role=user.role if user else None)

    app.logger.info('App initialized, logging configured. Logs writing to %s', log_path)

    return app