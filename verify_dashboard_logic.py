
import os
import sys
from dotenv import load_dotenv

# Load env
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path, override=True)
sys.path.append(os.path.dirname(__file__))

from blueprints.dashboard import get_dashboard_symbols

def check_logic():
    print("Checking get_dashboard_symbols()...")
    try:
        indices, stocks, mcx = get_dashboard_symbols()
        print(f"Indices: {len(indices)}")
        print(f"Stocks: {len(stocks)}")
        print(f"MCX: {len(mcx)}")
        
        for m in mcx:
            print(f"  MCX Item: {m}")
            
        if not mcx:
            print("FAILURE: No MCX symbols returned.")
        else:
            print("SUCCESS: MCX symbols returned.")
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_logic()
