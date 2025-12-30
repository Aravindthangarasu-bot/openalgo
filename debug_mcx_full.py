
import os
import sys
from dotenv import load_dotenv

# Load env vars
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path, override=True)

# Add current dir to sys.path
sys.path.append(os.path.dirname(__file__))

from database.symbol import db_session
from database.user_db import User
from database.auth_db import get_auth_token
from blueprints.dashboard import get_dashboard_symbols
from services.quotes_service import get_multiquotes

def debug_full_flow():
    # 1. Get User
    # Try 'admin' first, then 'aravind', then first
    user = db_session.query(User).filter(User.username == 'admin').first()
    if not user:
        user = db_session.query(User).filter(User.username == 'aravind').first()
    if not user:
        user = db_session.query(User).first()
        
    if not user:
        print("No user found in DB")
        return
    
    print(f"Testing for user: {user.username}")
    auth_token = get_auth_token(user.username)
    if not auth_token:
        print("Could not get auth token")
        return
        
    print(f"Auth Token: {auth_token[:10]}...")

    # 2. Get Symbols
    print("\nGetting dashboard symbols...")
    # Mocking get_analyze_mode context if needed? 
    # get_dashboard_symbols doesn't depend on session/user, just DB.
    indices, stocks, mcx = get_dashboard_symbols()
    
    print(f"MCX Symbols Found: {len(mcx)}")
    for s in mcx:
        print(f" - {s['symbol']} ({s['exchange']}) Exp: {s.get('expiry')}")

    if not mcx:
        print("CRITICAL: No MCX symbols returned by get_dashboard_symbols logic.")
        return

    # 3. Call Broker
    mcx_list = [{'symbol': s['symbol'], 'exchange': s['exchange']} for s in mcx]
    nifty = {'symbol': 'NIFTY', 'exchange': 'NSE'}
    all_symbols = [nifty] + mcx_list
    
    # We need broker name. Assuming 'angel' based on logs.
    broker = 'angel' 
    
    print(f"\nRequesting quotes for {len(all_symbols)} items (1 NIFTY + {len(mcx_list)} MCX) from {broker}...")
    success, response, code = get_multiquotes(
        symbols=all_symbols,
        auth_token=auth_token,
        broker=broker
    )
    
    print(f"Quote Success: {success}")
    if success:
        results = response.get('results', [])
        print(f"Results count: {len(results)}")
        for r in results:
            data = r.get('data')
            err = r.get('error')
            print(f"Symbol: {r.get('symbol')} | Exchange: {r.get('exchange')}")
            if data:
                print(f"  > LTP: {data.get('ltp')} | Vol: {data.get('volume')}")
            else:
                print(f"  > ERROR/EMPTY: {err}")
    else:
        print(f"Quote Failed: {response}")

if __name__ == "__main__":
    try:
        debug_full_flow()
    except Exception as e:
        print(f"Error: {e}")
