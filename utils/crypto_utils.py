# utils/crypto_utils.py
"""
Encryption/decryption utilities for storing sensitive credentials securely
Uses Fernet (symmetric encryption) from cryptography library
"""

from cryptography.fernet import Fernet
import os
import base64
import hashlib
from flask import current_app

def get_encryption_key():
    """
    Get or create the encryption key for Fernet
    In production, store this in environment variable: ENCRYPTION_KEY
    """
    # Try to get from environment
    env_key = os.environ.get('ENCRYPTION_KEY')
    if env_key:
        return env_key.encode() if isinstance(env_key, str) else env_key
    
    # Fallback: Generate from FLASK_SECRET_KEY (less ideal but works for dev)
    secret = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')
    # Generate 32-byte key from secret using PBKDF2-like approach
    key_material = hashlib.sha256(secret.encode()).digest()
    key = base64.urlsafe_b64encode(key_material)
    return key

def encrypt_credential(plaintext):
    """
    Encrypt sensitive credential (API key, token, etc.)
    
    Args:
        plaintext (str): The secret to encrypt
        
    Returns:
        str: Base64-encoded encrypted data
    """
    if not plaintext:
        return None
    
    try:
        key = get_encryption_key()
        cipher = Fernet(key)
        encrypted = cipher.encrypt(plaintext.encode())
        return encrypted.decode()  # Return as string for database storage
    except Exception as e:
        current_app.logger.error(f'Encryption failed: {e}')
        raise

def decrypt_credential(encrypted_data):
    """
    Decrypt sensitive credential
    
    Args:
        encrypted_data (str): The encrypted credential from database
        
    Returns:
        str: Decrypted plaintext secret
    """
    if not encrypted_data:
        return None
    
    try:
        key = get_encryption_key()
        cipher = Fernet(key)
        decrypted = cipher.decrypt(encrypted_data.encode())
        return decrypted.decode()
    except Exception as e:
        current_app.logger.error(f'Decryption failed: {e}')
        raise

def rotate_credentials_key(old_key, new_key):
    """
    Re-encrypt all credentials with new key (for key rotation)
    This is a helper for migration if needed
    """
    # This would be used in a migration script
    # For now, just documenting the pattern
    pass
