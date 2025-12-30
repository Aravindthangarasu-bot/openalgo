import os
import requests
import json
from database.auth_db import get_auth_token_dbquery, decrypt_token
from dotenv import load_dotenv

# Load env
load_dotenv()

def test_auth():
    print("\n--- Testing Angel Authentication ---")
    
    # 1. Get Broker API Key
    api_key = os.getenv('BROKER_API_KEY')
    print(f"BROKER_API_KEY from .env: {api_key[:5]}...{api_key[-5:] if api_key else ''} (Length: {len(api_key) if api_key else 0})")
    
    # 2. Get Auth Token for 'aravind'
    username = 'aravind'
    try:
        auth_obj = get_auth_token_dbquery(username)
        if not auth_obj:
            print(f"CRITICAL: No auth entry found for user '{username}' in DB.")
            return
        
        auth_token = decrypt_token(auth_obj.auth)
        # print(f"AUTH_TOKEN from DB: {auth_token[:10]}... (Length: {len(auth_token) if auth_token else 0})")
        print(f"AUTH_TOKEN from DB: Present (Length: {len(auth_token) if auth_token else 0})")
    except Exception as e:
        print(f"DB Error: {e}")
        return

    if not api_key or not auth_token:
        print("MISSING credentials. Cannot test.")
        return

    # 3. Test Request (Get RMS Limits - Lightweight check)
    url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/user/v1/getRMS"
    
    # Using 127.0.0.1 to see if that works better than 'CLIENT_LOCAL_IP'
    headers = {
        'Authorization': f'Bearer {auth_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-UserType': 'USER',
        'X-SourceID': 'WEB',
        'X-ClientLocalIP': '127.0.0.1', 
        'X-ClientPublicIP': '127.0.0.1',
        'X-MACAddress': 'MAC_ADDRESS',
        'X-PrivateKey': api_key
    }
    
    print(f"\nMaking GET request to {url}...")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"HTTP Status: {response.status_code}")
        print(f"Raw Response: {response.text}")
        
        try:
            data = response.json()
            if data.get('status') == True:
                print("\n✅ SUCCESS: Authentication is VALID!")
            else:
                print(f"\n❌ FAILURE: API returned error: {data.get('message')}")
                print(f"ErrorCode: {data.get('errorcode')}")
        except:
             print("Could not parse JSON response.")

    except Exception as e:
        print(f"Requests Exception: {e}")

    print("\n------------------------------------")

if __name__ == "__main__":
    # Minimal app context setup to access DB
    try:
        from app import app
        with app.app_context():
            test_auth()
    except ImportError:
        # Fallback if app import fails (path issues)
        print("Could not import app. Trying manual DB init if needed (skipped for now).")
