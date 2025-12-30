import os
import sys
from dotenv import load_dotenv

# Load env vars
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path, override=True)

# Add current dir to sys.path
sys.path.append(os.path.dirname(__file__))

from database.symbol import SymToken, db_session

def check_mcx():
    print("Checking MCX Symbols in DB...")
    
    # 1. Check count
    count = db_session.query(SymToken).filter(SymToken.exchange == 'MCX').count()
    print(f"Total MCX Symbols: {count}")
    
    if count == 0:
        print("NO MCX SYMBOLS FOUND!")
        return

    # 2. Check Instrument Types
    from sqlalchemy import distinct
    types = db_session.query(distinct(SymToken.instrumenttype)).filter(SymToken.exchange == 'MCX').all()
    print(f"MCX Instrument Types: {[t[0] for t in types]}")

    # 3. Check specific FUTCOM for CRUDEOIL
    print("\nChecking CRUDEOIL FUTCOM:")
    futcoms = db_session.query(SymToken).filter(
        SymToken.exchange == 'MCX',
        SymToken.instrumenttype == 'FUTCOM',
        SymToken.symbol.like('CRUDEOIL%')
    ).limit(5).all()
    
    if not futcoms:
        print("No CRUDEOIL FUTCOM found with current filters!")
        # Broaden search to see what IS there for futures
        print("\nBroad search for CRUDEOIL non-options:")
        others = db_session.query(SymToken).filter(
            SymToken.exchange == 'MCX',
            SymToken.symbol.like('CRUDEOIL%'),
            ~SymToken.instrumenttype.in_(['OPTFUT', 'CE', 'PE'])
        ).limit(10).all()
        for s in others:
            print(f"Symbol: {s.symbol}, Instr: {s.instrumenttype}")
    else:
        for s in futcoms:
            print(f"FUTCOM Found -> Symbol: {s.symbol}, Expiry: {s.expiry}")

if __name__ == "__main__":
    try:
        check_mcx()
    except Exception as e:
        print(f"Error: {e}")
