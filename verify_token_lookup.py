
import os
import sys
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path, override=True)

sys.path.append(os.path.dirname(__file__))

from database.token_db import get_token, get_br_symbol

def test_token(symbol, exchange):
    print(f"\nTesting {symbol} on {exchange}...")
    token = get_token(symbol, exchange)
    print(f"Token: {token}")
    
    br_symbol = get_br_symbol(symbol, exchange)
    print(f"BrSymbol: {br_symbol}")

if __name__ == "__main__":
    symbols = [
        'CRUDEOIL16JAN26FUT',
        'GOLDGUINEA31DEC25FUT',
        'NATURALGAS27JAN26FUT'
    ]
    
    for s in symbols:
        test_token(s, 'MCX')
