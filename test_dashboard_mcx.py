
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Load env vars
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path, override=True)

# Add current dir to sys.path
sys.path.append(os.path.dirname(__file__))

from database.symbol import SymToken, db_session

def get_active_future_test(base_symbol):
    print(f"\nTesting get_active_future for {base_symbol}...")
    try:
        # Search for symbols starting with base_symbol and ending with FUT or FUTCOM
        results = db_session.query(SymToken).filter(
            SymToken.symbol.like(f'{base_symbol}%FUT'),
            SymToken.exchange == 'MCX',
            SymToken.instrumenttype == 'FUTCOM'
        ).limit(30).all()
        
        print(f"Query returned {len(results)} results.")
        if not results:
            print("No results found in DB query.")
            return None
        
        today = datetime.now().date()
        active_futures = []
        
        for fut in results:
            if fut.expiry:
                print(f"Checking expiry: {fut.expiry} for symbol: {fut.symbol}")
                try:
                    # Try standard 4-digit year first
                    expiry_date = datetime.strptime(fut.expiry, '%d-%b-%Y').date()
                except ValueError:
                    try:
                        # Fallback to 2-digit year (common in MCX data)
                        expiry_date = datetime.strptime(fut.expiry, '%d-%b-%y').date()
                    except ValueError as e:
                        print(f"FAILED to parse date: {fut.expiry} - {e}")
                        continue

                if expiry_date >= today:
                    print(f"VALID: {expiry_date} >= {today}")
                    active_futures.append({
                        'symbol': fut.symbol,
                        'expiry': expiry_date
                    })
                else:
                    print(f"EXPIRED: {expiry_date} < {today}")
            else:
                print(f"No expiry for {fut.symbol}")
        
        if not active_futures:
            print("No active futures found after filtering.")
            return None
        
        # Sort by expiry (nearest first)
        active_futures.sort(key=lambda x: x['expiry'])
        
        nearest = active_futures[0]
        print(f"Selected NEAREST: {nearest['symbol']}")
        
        return {
            'symbol': nearest['symbol'],
            'exchange': 'MCX_FO',
            'display_name': base_symbol.title()
        }
    except Exception as e:
        print(f"Error checking MCX future for {base_symbol}: {e}")
        return None

if __name__ == "__main__":
    for commodity in ['CRUDEOIL', 'GOLD', 'NATURALGAS']:
        get_active_future_test(commodity)
