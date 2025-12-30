from flask import Blueprint, render_template, session, redirect, url_for, jsonify
from functools import wraps
from database.auth_db import get_auth_token, get_api_key_for_tradingview
from database.settings_db import get_analyze_mode
from services.funds_service import get_funds
from services.quotes_service import get_multiquotes
from utils.session import check_session_validity
from utils.logging import get_logger

logger = get_logger(__name__)

def safe_dashboard_view(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Dashboard Critical Error: {e}", exc_info=True)
            return render_template('500.html', error=str(e)), 500
    return decorated_function


dashboard_bp = Blueprint('dashboard_bp', __name__, url_prefix='/')
scalper_process = None

@dashboard_bp.route('/dashboard')
@check_session_validity
@safe_dashboard_view
def dashboard():
    login_username = session['user']
    AUTH_TOKEN = get_auth_token(login_username)

    # Initialize empty data structures
    margin_data = {}
    indices_data = []
    mcx_data = []
    stocks_data = []
    telegram_status = {}
    
    # Try to fetch data if authenticated
    if AUTH_TOKEN:
        broker = session.get('broker')
        if broker:
            if get_analyze_mode():
                api_key = get_api_key_for_tradingview(login_username)
                if api_key:
                    success, response, status_code = get_funds(api_key=api_key)
                    if success:
                        margin_data = response.get('data', {})
            else:
                success, response, status_code = get_funds(auth_token=AUTH_TOKEN, broker=broker)
                if success:
                    margin_data = response.get('data', {})
    
    # Get symbols using shared helper
    indices_symbols, stocks_symbols, mcx_symbols = get_dashboard_symbols()
    
    try:
        # Combine all for a single fetch
        all_symbols_to_fetch = indices_symbols + stocks_symbols + [{'symbol': s['symbol'], 'exchange': s['exchange']} for s in mcx_symbols]
        
        # Fetch quotes
        # Fetch quotes
        qt_success, qt_response, _ = get_multiquotes(
            symbols=all_symbols_to_fetch,
            auth_token=AUTH_TOKEN,
            broker=session.get('broker')
        )

        # DEBUG LOGGING for MCX
        logger.info(f"DEBUG: Dashboard fetching {len(mcx_symbols)} MCX symbols")
        if mcx_symbols:
            logger.info(f"DEBUG: MCX Request Symbols: {[s['symbol'] for s in mcx_symbols]}")

        if qt_success:
            all_results = qt_response.get('results', [])
            # Map results by "exchange:symbol" for easy lookup
            results_map = {}
            for r in all_results:
                # Handle cases where result keys might vary
                key_sym = r.get('symbol', '')
                key_exc = r.get('exchange', '').upper()
                results_map[f"{key_exc}:{key_sym}"] = r
                
                # DEBUG Log for MCX results
                if key_exc == 'MCX':
                    logger.info(f"DEBUG: MCX Result: {key_sym} -> Data present: {r.get('data') is not None}")

            
            # Populate NSE/BSE Indices
            for req in indices_symbols:
                key = f"{req['exchange']}:{req['symbol']}"
                if key in results_map:
                    indices_data.append(results_map[key])
            
            # Populate Stocks
            for req in stocks_symbols:
                key = f"{req['exchange']}:{req['symbol']}"
                if key in results_map:
                    stocks_data.append(results_map[key])

            # Populate MCX (map back to friendly names)
            for req in mcx_symbols:
                # Try MCX first
                key = f"{req['exchange']}:{req['symbol']}"
                
                # Fallback to MCX_FO if not found (common Broker response vs Request mismatch)
                if key not in results_map and req['exchange'] == 'MCX':
                     key = f"MCX_FO:{req['symbol']}"
                     
                if key in results_map:
                    data = results_map[key]
                    data['display_name'] = req.get('display_name', req['symbol'])
                    mcx_data.append(data)
                    
        else:
            logger.warning(f"Failed to fetch indices: {qt_response.get('message')}")
            
    except Exception as e:
        logger.error(f"Error fetching dashboard data: {e}", exc_info=True)

    # Debug Margin Data
    logger.info(f"Dashboard Margin Data for {login_username}: {margin_data}")

    try:
        from services.telegram_listener_service import telegram_listener
        # Resolve channel names for display
        display_channels = []
        if telegram_listener and hasattr(telegram_listener, 'channels') and telegram_listener.channels:
            for c in telegram_listener.channels:
                display_channels.append(telegram_listener.channel_map.get(c, str(c)))

        telegram_status = {
            'is_running': getattr(telegram_listener, 'is_running', False),
            'target_channel': getattr(telegram_listener, 'target_channel', None),
            'channels': display_channels
        }
    except Exception as e:
        logger.error(f"Error getting Telegram status: {e}")
        telegram_status = {'is_running': False, 'channels': []}

    try:
        return render_template('dashboard.html', 
                             margin_data=margin_data, 
                             indices_data=indices_data,
                             mcx_data=mcx_data,
                             stocks_data=stocks_data,
                             telegram_status=telegram_status)
    except Exception as e:
        logger.error(f"Template rendering error: {e}", exc_info=True)
        raise e


def get_dashboard_symbols():
    """Helper to get the list of symbols to display on dashboard"""
    # NSE/BSE Indices
    indices_symbols = [
        {'symbol': 'NIFTY', 'exchange': 'NSE_INDEX'},
        {'symbol': 'BANKNIFTY', 'exchange': 'NSE_INDEX'},
        {'symbol': 'FINNIFTY', 'exchange': 'NSE_INDEX'},
        {'symbol': 'SENSEX', 'exchange': 'BSE_INDEX'},
        {'symbol': 'BANKEX', 'exchange': 'BSE_INDEX'}
    ]
    
    # Top 10 NSE Stocks
    stocks_symbols = [
        {'symbol': 'RELIANCE', 'exchange': 'NSE'},
        {'symbol': 'HDFCBANK', 'exchange': 'NSE'},
        {'symbol': 'INFY', 'exchange': 'NSE'},
        {'symbol': 'TCS', 'exchange': 'NSE'},
        {'symbol': 'ICICIBANK', 'exchange': 'NSE'},
        {'symbol': 'KOTAKBANK', 'exchange': 'NSE'},
        {'symbol': 'LT', 'exchange': 'NSE'},
        {'symbol': 'AXISBANK', 'exchange': 'NSE'},
        {'symbol': 'ITC', 'exchange': 'NSE'},
        {'symbol': 'SBIN', 'exchange': 'NSE'}
    ]
    
    # MCX Indices (Active Futures)
    mcx_symbols = []
    try:
        from database.symbol import db_session, SymToken
        from datetime import datetime
        
        # Helper to find nearest active future
        def get_active_future(base_symbol):
            # Query database directly for futures
            try:
                # Search for symbols starting with base_symbol and ending with FUT or FUTCOM
                results = db_session.query(SymToken).filter(
                    SymToken.symbol.like(f'{base_symbol}%FUT'),
                    SymToken.exchange == 'MCX',
                    SymToken.instrumenttype == 'FUTCOM'
                ).limit(30).all()
                
                if not results:
                    return None
                
                today = datetime.now().date()
                active_futures = []
                
                for fut in results:
                    if fut.expiry:
                        expiry_date = None
                        try:
                            # Try standard 4-digit year first
                            expiry_date = datetime.strptime(fut.expiry, '%d-%b-%Y').date()
                        except ValueError:
                            try:
                                # Fallback to 2-digit year (common in MCX data)
                                expiry_date = datetime.strptime(fut.expiry, '%d-%b-%y').date()
                            except ValueError:
                                continue

                        if expiry_date and expiry_date >= today:
                            active_futures.append({
                                'symbol': fut.symbol,
                                'expiry': expiry_date
                            })
                
                if not active_futures:
                    return None
                
                # Sort by expiry (nearest first)
                active_futures.sort(key=lambda x: x['expiry'])
                
                # Logic to prefer specific active contracts if needed, else nearest
                nearest = active_futures[0]
                
                return {
                    'symbol': nearest['symbol'],
                    'exchange': 'MCX', 
                    'display_name': base_symbol.title()
                }
            except Exception as e:
                logger.error(f"Error checking MCX future for {base_symbol}: {e}")
                return None

        for commodity in ['CRUDEOIL', 'GOLD', 'NATURALGAS']:
            future = get_active_future(commodity)
            if future:
                # Angel One specific adjustment if needed, usually 'MCX' works for quote fetch
                future['exchange'] = 'MCX' 
                mcx_symbols.append(future)
                
    except Exception as e:
        logger.error(f"Error generating MCX symbols: {e}")
        
    return indices_symbols, stocks_symbols, mcx_symbols


@dashboard_bp.route('/api/mcx/expiries/<commodity>')
@check_session_validity
def get_mcx_expiries(commodity):
    """API endpoint to get all available expiries for an MCX commodity"""
    try:
        from datetime import datetime
        from database.symbol import db_session, SymToken
        
        # Query all FUTCOM contracts for this commodity
        results = db_session.query(SymToken).filter(
            SymToken.symbol.like(f'{commodity.upper()}%FUT'),
            SymToken.exchange == 'MCX',
            SymToken.instrumenttype == 'FUTCOM'
        ).all()
        
        if not results:
            return jsonify({'error': f'No contracts found for {commodity}'}), 404
        
        # Parse and format expiries
        expiries = []
        today = datetime.now().date()
        
        for contract in results:
            try:
                if contract.expiry:
                    try:
                        expiry_date = datetime.strptime(contract.expiry, '%d-%b-%Y').date()
                    except ValueError:
                         expiry_date = datetime.strptime(contract.expiry, '%d-%b-%y').date()
                    
                    is_active = expiry_date >= today
                    
                    # Format display name (e.g., "FEB 2026")
                    display_name = expiry_date.strftime('%b %Y').upper()
                    
                    expiries.append({
                        'symbol': contract.symbol,
                        'expiry_date': expiry_date.isoformat(),
                        'display_name': display_name,
                        'is_active': is_active
                    })
            except (ValueError, TypeError):
                continue
        
        # Sort by expiry date
        expiries.sort(key=lambda x: x['expiry_date'])
        
        # Mark nearest active
        active_expiries = [e for e in expiries if e['is_active']]
        if active_expiries:
            active_expiries[0]['is_nearest'] = True
        
        return jsonify({
            'commodity': commodity.upper(),
            'expiries': expiries
        })
        
    except Exception as e:
        logger.error(f"Error fetching expiries for {commodity}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


import time

# Simple in-memory cache: {(user_id, endpoint): {'data': response_data, 'timestamp': time.time()}}
API_CACHE = {}
CACHE_TTL = 1  # 1 second cache

@dashboard_bp.route('/api/dashboard/prices')
@check_session_validity
def get_dashboard_prices():
    """API endpoint for live price updates - returns JSON"""
    try:
        login_username = session['user']
        
        # Check Cache
        cache_key = (login_username, 'dashboard_prices')
        cached = API_CACHE.get(cache_key)
        if cached and (time.time() - cached['timestamp'] < CACHE_TTL):
            return jsonify(cached['data'])

        AUTH_TOKEN = get_auth_token(login_username)
        
        if AUTH_TOKEN is None:
            return jsonify({'error': 'No auth token'}), 401
        
        # Get symbols using shared helper
        indices_symbols, stocks_symbols, mcx_symbols = get_dashboard_symbols()
        
        # Combine all symbols
        all_symbols_to_fetch = indices_symbols + stocks_symbols + [{'symbol': s['symbol'], 'exchange': s['exchange']} for s in mcx_symbols]
        
        # Fetch quotes
        qt_success, qt_response, _ = get_multiquotes(
            symbols=all_symbols_to_fetch,
            auth_token=AUTH_TOKEN,
            broker=session.get('broker')
        )
        
        if not qt_success:
            return jsonify({'error': 'Failed to fetch quotes'}), 500
        
        all_results = qt_response.get('results', [])
        results_map = {}
        for r in all_results:
             key_sym = r.get('symbol', '')
             key_exc = r.get('exchange', '')
             results_map[f"{key_exc}:{key_sym}"] = r
             # Also try relaxed key (just symbol) for easier matching if exchange is ambiguous
             results_map[key_sym] = r

        # Structure response
        response_data = {
            'indices': [],
            'stocks': [],
            'mcx': []
        }
        
        # Process indices
        for req in indices_symbols:
            key = f"{req['exchange']}:{req['symbol']}"
            data = results_map.get(key)
            if data:
                # Handle 'lp' or 'ltp' or nested 'd'
                val = data.get('lp') or data.get('ltp')
                if val is None and 'data' in data:
                     val = data['data'].get('lp') or data['data'].get('ltp')
                     
                response_data['indices'].append({
                    'symbol': req['symbol'],
                    'lp': val if val else 0,
                    'pc': data.get('pc', data.get('percentChange', 0))
                })
        
        # Process stocks
        for req in stocks_symbols:
            key = f"{req['exchange']}:{req['symbol']}"
            data = results_map.get(key)
            if data:
                val = data.get('lp') or data.get('ltp')
                if val is None and 'data' in data:
                     val = data['data'].get('lp') or data['data'].get('ltp')

                response_data['stocks'].append({
                    'symbol': req['symbol'],
                    'lp': val if val else 0,
                    'pc': data.get('pc', data.get('percentChange', 0))
                })
        
        # Process MCX
        for req in mcx_symbols:
            key = f"{req['exchange']}:{req['symbol']}"
            
            # Fallback logic parity with dashboard() route
            if key not in results_map and req['exchange'] == 'MCX':
                 key_fo = f"MCX_FO:{req['symbol']}"
                 if key_fo in results_map:
                     key = key_fo

            data = results_map.get(key)
            if data:
                val = data.get('lp') or data.get('ltp')
                if val is None and 'data' in data:
                     val = data['data'].get('lp') or data['data'].get('ltp')

                response_data['mcx'].append({
                    'symbol': req.get('display_name', req['symbol']),
                    'lp': val if val else 0,
                    'pc': data.get('pc', data.get('percentChange', 0))
                })
            else:
                 logger.debug(f"DEBUG API: MCX Symbol {req['symbol']} not found in results map. Keys tried: {key}")
        
        # Update Cache
        API_CACHE[cache_key] = {'data': response_data, 'timestamp': time.time()}

        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error fetching prices API: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

from flask import request
from database.settings_db import get_trading_lots, set_trading_lots

@dashboard_bp.route('/api/settings/lots', methods=['GET', 'POST'])
@check_session_validity
def handle_lots_setting():
    """Get or Set global trading lots multiplier"""
    try:
        if request.method == 'GET':
            return jsonify({'lots': get_trading_lots()})
        
        if request.method == 'POST':
            data = request.json
            if not data or 'lots' not in data:
                return jsonify({'error': 'Missing lots value'}), 400
            
            try:
                lots = int(data['lots'])
                if lots < 1:
                    return jsonify({'error': 'Lots must be at least 1'}), 400
                if lots > 100:
                    return jsonify({'error': 'Lots cannot exceed 100'}), 400
                    
                set_trading_lots(lots)
                return jsonify({'success': True, 'lots': lots, 'message': f'Trading lots updated to {lots}'})
            except ValueError:
                return jsonify({'error': 'Invalid integer value'}), 400
                
    except Exception as e:
        logger.error(f"Error handling lots setting: {e}")
        return jsonify({'error': str(e)}), 500 
