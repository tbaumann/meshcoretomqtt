#!/usr/bin/env python3
"""
MeshCore Auth Token Generator
Generates JWT-style authentication tokens for MQTT authentication
"""
import json
import base64
import hashlib
import time
import subprocess
import sys

def base64url_encode(data: bytes) -> str:
    """Base64url encode without padding"""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')

def create_auth_token(public_key_hex: str, private_key_hex: str, expiry_seconds: int = 3600, **claims) -> str:
    """
    Create a JWT-style auth token for MeshCore MQTT authentication
    
    Uses the meshcore-decoder CLI tool.
    
    Args:
        public_key_hex: 32-byte public key in hex format
        private_key_hex: 64-byte private key in hex format (MeshCore format)
        expiry_seconds: Token expiry time in seconds (default 24 hours)
        **claims: Additional JWT claims (e.g., audience="mqtt.example.com", sub="device-123")
    
    Returns:
        JWT-style token string
    """
    try:
        cmd = ['meshcore-decoder', 'auth-token', public_key_hex, private_key_hex, '-e', str(expiry_seconds)]
        
        if claims:
            claims_json = json.dumps(claims)
            cmd.extend(['-c', claims_json])
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            raise Exception(f"meshcore-decoder error: {result.stderr}")
        
        token = result.stdout.strip()
        if not token or token.count('.') != 2:
            raise Exception(f"Invalid token format: {token}")
        
        return token
        
    except subprocess.TimeoutExpired:
        raise Exception("Token generation timed out")
    except FileNotFoundError:
        raise Exception("meshcore-decoder CLI not found. Please install: npm install -g @michaelhart/meshcore-decoder")
    except Exception as e:
        raise Exception(f"Failed to generate auth token: {str(e)}")

def read_private_key_file(filepath: str) -> str:
    """Read private key from file (64-byte hex format)"""
    try:
        with open(filepath, 'r') as f:
            key = f.read().strip()
            key = ''.join(key.split())
            if len(key) != 128:  # 64 bytes = 128 hex chars
                raise ValueError(f"Invalid private key length: {len(key)} (expected 128)")
            int(key, 16)
            return key
    except FileNotFoundError:
        raise Exception(f"Private key file not found: {filepath}")
    except ValueError as e:
        raise Exception(f"Invalid private key format: {str(e)}")

if __name__ == "__main__":
    # Test/CLI usage
    if len(sys.argv) < 3:
        print("Usage: python auth_token.py <public_key_hex> <private_key_hex_or_file>")
        sys.exit(1)
    
    public_key = sys.argv[1]
    private_key_input = sys.argv[2]
    
    if len(private_key_input) < 128:
        try:
            private_key = read_private_key_file(private_key_input)
            print(f"Loaded private key from: {private_key_input}")
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)
    else:
        private_key = private_key_input
    
    try:
        token = create_auth_token(public_key, private_key)
        print(f"Generated token: {token}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
