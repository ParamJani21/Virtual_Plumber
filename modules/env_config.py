"""
Environment Configuration Manager
Handles reading and writing .env file for storing credentials
Location: Root directory .env file
"""

import os
from pathlib import Path
from typing import Dict, Optional


class EnvConfigManager:
    """Manages .env file operations for storing credentials securely"""
    
    def __init__(self, env_path: Optional[str] = None):
        """
        Initialize EnvConfigManager
        
        Args:
            env_path: Path to .env file. Defaults to root/.env
        """
        if env_path is None:
            # Get root directory (VIRTUAL_PLUMBER folder parent or itself)
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.env_path = os.path.join(root_dir, '.env')
        else:
            self.env_path = env_path
    
    def read_env(self) -> Dict[str, str]:
        """
        Read .env file and return as dictionary
        Handles RSA keys with escaped newlines (\n in the file)
        
        Returns:
            Dictionary of environment variables
        """
        env_vars = {}
        
        if not os.path.exists(self.env_path):
            return env_vars
        
        try:
            with open(self.env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        
                        # Convert escaped newlines (\n) to actual newlines
                        value = value.replace('\\n', '\n')
                        
                        env_vars[key] = value
        
        except Exception as e:
            print(f"Error reading .env file: {e}")
        
        return env_vars
    
    def write_env(self, env_vars: Dict[str, str]) -> bool:
        """
        Write environment variables to .env file
        Escapes newlines as \n for multiline values like RSA keys
        
        Args:
            env_vars: Dictionary of environment variables to write
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.env_path) or '.', exist_ok=True)
            
            with open(self.env_path, 'w', encoding='utf-8') as f:
                for key, value in env_vars.items():
                    # Escape newlines as \n for multiline values
                    value_str = str(value).replace('\n', '\\n')
                    
                    # Quote values if they contain spaces or special characters
                    if ' ' in value_str or '\\n' in value_str:
                        f.write(f'{key}="{value_str}"\n')
                    else:
                        f.write(f'{key}={value_str}\n')
            
            return True
        
        except Exception as e:
            print(f"Error writing to .env file: {e}")
            return False
    
    def get_setting(self, key: str, default: str = "") -> str:
        """
        Get a specific environment variable
        
        Args:
            key: Environment variable key
            default: Default value if key not found
        
        Returns:
            Environment variable value or default
        """
        env_vars = self.read_env()
        return env_vars.get(key, default)
    
    def set_setting(self, key: str, value: str) -> bool:
        """
        Set a specific environment variable
        
        Args:
            key: Environment variable key
            value: Environment variable value
        
        Returns:
            True if successful, False otherwise
        """
        env_vars = self.read_env()
        env_vars[key] = str(value)
        return self.write_env(env_vars)
    
    def get_github_credentials(self) -> Dict[str, str]:
        """
        Get all GitHub-related credentials from .env
        
        Returns:
            Dictionary with GitHub settings
        """
        env_vars = self.read_env()
        return {
            'github_app_id': env_vars.get('GITHUB_APP_ID', ''),
            'github_app_name': env_vars.get('GITHUB_APP_NAME', ''),
            'github_secret_key': env_vars.get('GITHUB_SECRET_KEY', ''),
            'ngrok_oauth_token': env_vars.get('NGROK_OAUTH_TOKEN', ''),
            'github_webhook_secret': env_vars.get('GITHUB_WEBHOOK_SECRET', '')
        }

    def get_snyk_token(self) -> str:
        """Get Snyk API token from .env"""
        env_vars = self.read_env()
        return env_vars.get('SNYK_TOKEN', '')
    
    def save_setting(self, key: str, value: str) -> bool:
        """
        Save a single setting to .env file
        
        Args:
            key: Environment variable key
            value: Environment variable value
        
        Returns:
            True if successful, False otherwise
        """
        env_vars = self.read_env()
        env_vars[key] = str(value)
        return self.write_env(env_vars)
    
    def save_github_credentials(self, 
                               app_id: str = '',
                               app_name: str = '',
                               secret_key: str = '',
                               oauth_token: str = '',
                               webhook_secret: str = '') -> bool:
        """
        Save GitHub-related credentials to .env
        
        Args:
            app_id: GitHub App ID
            app_name: GitHub App Name
            secret_key: GitHub Secret Key
            oauth_token: ngrok OAuth Token
            webhook_secret: GitHub Webhook Secret for signature verification
        
        Returns:
            True if successful, False otherwise
        """
        env_vars = self.read_env()
        
        # Only update if values provided
        if app_id:
            env_vars['GITHUB_APP_ID'] = str(app_id).strip()
        if app_name:
            env_vars['GITHUB_APP_NAME'] = str(app_name).strip()
        if secret_key:
            env_vars['GITHUB_SECRET_KEY'] = str(secret_key).strip()
        if oauth_token:
            env_vars['NGROK_OAUTH_TOKEN'] = str(oauth_token).strip()
        if webhook_secret:
            env_vars['GITHUB_WEBHOOK_SECRET'] = str(webhook_secret).strip()
        
        return self.write_env(env_vars)


# Global instance
env_config = EnvConfigManager()
