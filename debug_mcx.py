from app import app
from database.token_db_enhanced import get_cache

with app.app_context():
    cache = get_cache()
    # Force load if needed, though app context might not trigger it unless we mock it or call load
    # simulation of load:
    # cache.load_all_symbols('ANGELONE') # assuming broker is angelone
    
    # Actually, let's just inspect what's in the DB first for MCX
    from database.symbol import SymToken
    
    print("Checking MCX Symbols in DB:")
    samples = SymToken.query.filter_by(exchange='MCX').limit(5).all()
    for s in samples:
        print(f"Symbol: {s.symbol}, Name: {s.name}, Instr: {s.instrumenttype}, Expiry: {s.expiry}")
        
    print("\nTesting fno_search_symbols for CRUDEOIL:")
    # We need to load cache for this to work, but loading cache might take time/memory.
    # Let's try direct DB query similar to what valid_symbol_search does if cache fails
    
    # Verify what 'instrumenttype' looks like for MCX Futures
    crude = SymToken.query.filter(SymToken.symbol.like('CRUDEOIL%')).first()
    if crude:
        print(f"Sample CRUDE: {crude.symbol} {crude.instrumenttype} {crude.exchange}")
