#!/usr/bin/env python3
"""
MTProto Downloader — uses Telethon user session to download files up to 2GB.
Run once locally to generate session string, then store in GitHub secrets.
"""
import os
import sys
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# Your credentials (already configured)
API_ID = 36325364
API_HASH = '5f03f8bfeddec2cf2c1b30c9692b54ff'
PHONE = '+916303772091'

def create_session():
    """Run this ONCE locally to generate session string."""
    print("Creating Telethon session...")
    print("Using OTP: 82166")
    
    client = TelegramClient(StringSession(), 36325364, '5f03f8bfeddec2cf2c1b30c9692b54ff')
    client.connect()
    
    if not client.is_user_authorized():
        client.send_code_request('+916303772091')
        # Use the provided OTP
        code = '82166'
        print(f"Using OTP: {code}")
        client.sign_in('+916303772091', code)
    
    session_string = client.session.save()
    print("\n=== SESSION STRING (save this to GitHub Secrets as TELETHON_SESSION) ===")
    print(session_string)
    print("\n=== Also save these to GitHub Secrets ===")
    print("TELEGRAM_API_ID=36325364")
    print("TELEGRAM_API_HASH=5f03f8bfeddec2cf2c1b30c9692b54ff")
    print("TELEGRAM_PHONE=+916303772091")
    
    with open('.telethon_session', 'w') as f:
        f.write(session_string)
    
    print("\nSession saved to .telethon_session")
    client.disconnect()

if __name__ == '__main__':
    create_session()