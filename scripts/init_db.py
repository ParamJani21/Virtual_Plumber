#!/usr/bin/env python3
# scripts/init_db.py
"""
Initialize VIRTUAL_PLUMBER database
Creates tables and sets up initial admin if needed
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from models.database import db, User, UserPreferences
from datetime import datetime
import secrets
import string


def init_database():
    """Initialize database and create tables"""
    app = create_app()
    
    with app.app_context():
        print("Initializing database...")
        
        # Create all tables
        try:
            db.create_all()
            print("✓ Database tables created successfully")
        except Exception as e:
            print(f"✗ Error creating database tables: {e}")
            return False
        
        # Check if any admin exists
        admin_exists = User.query.filter_by(role='admin').first()
        
        if admin_exists:
            print("✓ Admin user already exists, skipping initial admin setup")
            return True
        
        print("\n" + "="*60)
        print("INITIAL ADMIN SETUP")
        print("="*60)
        
        # Prompt for admin details
        while True:
            username = input("\nEnter admin username (4-20 alphanumeric characters): ").strip()
            
            if len(username) < 4 or len(username) > 20:
                print("✗ Username must be 4-20 characters")
                continue
            
            if not username.replace('_', '').replace('-', '').isalnum():
                print("✗ Username can only contain letters, numbers, underscore, and hyphen")
                continue
            
            # Check if username already exists
            if User.query.filter_by(username=username).first():
                print("✗ Username already exists")
                continue
            
            break
        
        email = input("Enter admin email (optional): ").strip()
        if email and '@' not in email:
            print("✗ Invalid email format")
            email = None
        
        while True:
            password = input("Enter admin password (12+ chars, uppercase, lowercase, number, special char): ")
            
            # Basic password validation
            if len(password) < 12:
                print("✗ Password must be at least 12 characters")
                continue
            
            if not any(c.isupper() for c in password):
                print("✗ Password must contain uppercase letter")
                continue
            
            if not any(c.islower() for c in password):
                print("✗ Password must contain lowercase letter")
                continue
            
            if not any(c.isdigit() for c in password):
                print("✗ Password must contain number")
                continue
            
            if not any(c in '!@#$%^&*' for c in password):
                print("✗ Password must contain special character (!@#$%^&*)")
                continue
            
            confirm = input("Confirm password: ")
            
            if password != confirm:
                print("✗ Passwords do not match")
                continue
            
            break
        
        # Create admin user
        try:
            user = User(
                username=username,
                email=email or None,
                password_hash=User.hash_password(password),
                is_first_login=True,
                account_status='active',
                role='admin',
                last_login=datetime.utcnow()
            )
            
            db.session.add(user)
            db.session.commit()
            
            # Create default preferences
            preferences = UserPreferences(user_id=user.id)
            db.session.add(preferences)
            db.session.commit()
            
            print(f"\n✓ Admin user '{username}' created successfully")
            print(f"  Email: {email or 'Not set'}")
            print(f"  Role: admin")
            print(f"  Status: active")
            
            return True
        
        except Exception as e:
            print(f"\n✗ Error creating admin user: {e}")
            db.session.rollback()
            return False


def main():
    """Main entry point"""
    print("VIRTUAL_PLUMBER - Database Initialization")
    print("="*60)
    
    success = init_database()
    
    if success:
        print("\n✓ Database initialization complete!")
        print("  You can now start the application with: python3 run.py")
        print("  Login with your admin credentials at: http://localhost:5000/login")
        return 0
    else:
        print("\n✗ Database initialization failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
