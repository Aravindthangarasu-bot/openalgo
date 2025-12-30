from flask import Blueprint, jsonify, request, render_template, session, redirect, url_for, Response
from importlib import import_module
from database.auth_db import get_auth_token, get_api_key_for_tradingview
from database.settings_db import get_analyze_mode
from utils.session import check_session_validity
from services.place_smart_order_service import place_smart_order
from services.close_position_service import close_position
from services.orderbook_service import get_orderbook
from services.tradebook_service import get_tradebook
from services.positionbook_service import get_positionbook
from services.holdings_service import get_holdings
from services.position_monitor_service import position_monitor
from services.quotes_service import get_quotes, get_multiquotes
from utils.logging import get_logger
from limiter import limiter
import csv
import io
import os

logger = get_logger(__name__)

# Use existing rate limits from .env
API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "50 per second")

# Define the blueprint
orders_bp = Blueprint('orders_bp', __name__, url_prefix='/')

@orders_bp.errorhandler(429)
def ratelimit_handler(e):
    """Handle rate limit exceeded errors"""
    return jsonify({
        'status': 'error',
        'message': 'Rate limit exceeded. Please try again later.'
    }), 429

import time

# Simple in-memory cache: {(user_id, endpoint): {'data': response_data, 'timestamp': time.time()}}
API_CACHE = {}
CACHE_TTL = 1  # 1 second cache

@orders_bp.route('/api/orders')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def get_orders_api():
    """API endpoint to fetch orders (JSON) with Caching"""
    login_username = session['user']
    
    # Check Cache
    cache_key = (login_username, 'orders')
    cached = API_CACHE.get(cache_key)
    if cached and (time.time() - cached['timestamp'] < CACHE_TTL):
        return jsonify(cached['data'])

    auth_token = get_auth_token(login_username)

    if auth_token is None:
        return jsonify({'status': 'error', 'message': 'Authentication failed'}), 401

    broker = session.get('broker')
    if not broker:
        return jsonify({'status': 'error', 'message': 'Broker not set'}), 400

    if get_analyze_mode():
        api_key = get_api_key_for_tradingview(login_username)
        if api_key:
            success, response, status_code = get_orderbook(api_key=api_key)
        else:
            return jsonify({'status': 'error', 'message': 'API key required'}), 400
    else:
        success, response, status_code = get_orderbook(auth_token=auth_token, broker=broker)

    if not success:
        return jsonify({'status': 'error', 'message': response.get('message', 'Failed to fetch orders')}), status_code

    data = response.get('data', {})
    orders = data.get('orders', [])
    orders = enrich_orders_with_ltp(orders, login_username, auth_token, broker)
    data['orders'] = orders
    
    # Update Cache
    API_CACHE[cache_key] = {'data': data, 'timestamp': time.time()}
    
    return jsonify(data)

@orders_bp.route('/api/trades')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def get_trades_api():
    """API endpoint to fetch trades (JSON) with Caching"""
    login_username = session['user']
    
    # Check Cache
    cache_key = (login_username, 'trades')
    cached = API_CACHE.get(cache_key)
    if cached and (time.time() - cached['timestamp'] < CACHE_TTL):
        return jsonify(cached['data'])
        
    auth_token = get_auth_token(login_username)

    if auth_token is None:
        return jsonify({'status': 'error', 'message': 'Authentication failed'}), 401

    broker = session.get('broker')
    if not broker:
        return jsonify({'status': 'error', 'message': 'Broker not set'}), 400

    if get_analyze_mode():
        api_key = get_api_key_for_tradingview(login_username)
        if api_key:
            success, response, status_code = get_tradebook(api_key=api_key)
        else:
            return jsonify({'status': 'error', 'message': 'API key required'}), 400
    else:
        success, response, status_code = get_tradebook(auth_token=auth_token, broker=broker)

    if not success:
        return jsonify({'status': 'error', 'message': response.get('message', 'Failed to fetch trades')}), status_code

    trades = response.get('data', [])
    # trades = enrich_trades_with_ltp(trades, login_username, auth_token, broker) # Removed
    
    response_data = {'trades': trades}
    
    # Update Cache
    API_CACHE[cache_key] = {'data': response_data, 'timestamp': time.time()}

    return jsonify(response_data)

@orders_bp.route('/api/positions')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def get_positions_api():
    """API endpoint to fetch positions (JSON) with Caching"""
    login_username = session['user']
    
    # Check Cache
    cache_key = (login_username, 'positions')
    cached = API_CACHE.get(cache_key)
    if cached and (time.time() - cached['timestamp'] < CACHE_TTL):
        return jsonify(cached['data'])
        
    auth_token = get_auth_token(login_username)

    if auth_token is None:
        return jsonify({'status': 'error', 'message': 'Authentication failed'}), 401

    broker = session.get('broker')
    if not broker:
        return jsonify({'status': 'error', 'message': 'Broker not set'}), 400

    if get_analyze_mode():
        api_key = get_api_key_for_tradingview(login_username)
        if api_key:
            success, response, status_code = get_positionbook(api_key=api_key)
        else:
            return jsonify({'status': 'error', 'message': 'API key required'}), 400
    else:
        success, response, status_code = get_positionbook(auth_token=auth_token, broker=broker)

    if not success:
        return jsonify({'status': 'error', 'message': response.get('message', 'Failed to fetch positions')}), status_code

    positions = response.get('data', [])
    
    # Enrich positions with SL/Target from monitor
    positions = enrich_positions_with_monitor(positions)
    
    # Enrich positions with real-time LTP data
    positions = enrich_positions_with_ltp(positions, login_username, auth_token, broker)
    
    response_data = {'data': positions}
    
    # Update Cache
    API_CACHE[cache_key] = {'data': response_data, 'timestamp': time.time()}

    return jsonify(response_data)




def enrich_positions_with_monitor(positions):
    """Enrich positions with SL/Target data from PositionMonitor"""
    try:
        if not positions:
            return positions
            
        active_monitored = position_monitor.get_active_positions()
        # Create a lookup map: (symbol, product, exchange) -> position_data
        monitor_map = {}
        for pid, pdata in active_monitored.items():
            sym = pdata.get('symbol')
            prod = pdata.get('product', 'MIS')
            exc = pdata.get('exchange')
            
            # Key 1: Strict match
            monitor_map[(sym, prod, exc)] = pdata
            
            # Key 2: Relaxed match (ignore product) - Store if not already present
            if (sym, exc) not in monitor_map:
                monitor_map[(sym, exc)] = pdata
        
        logger.info(f"Monitor Map Keys: {list(monitor_map.keys())}")
            
        for pos in positions:
            sym = pos.get('symbol')
            prod = pos.get('product')
            exc = pos.get('exchange')
            
            key_strict = (sym, prod, exc)
            key_relaxed = (sym, exc)
            
            m_pos = None
            if key_strict in monitor_map:
                m_pos = monitor_map[key_strict]
                logger.info(f"Position Match (Strict): {key_strict}")
            elif key_relaxed in monitor_map:
                m_pos = monitor_map[key_relaxed]
                logger.info(f"Position Match (Relaxed): {key_relaxed}")
            else:
                 logger.debug(f"Position No Match: {key_strict}")

                
            if m_pos:
                pos['current_sl'] = m_pos.get('current_sl')
                pos['final_target'] = m_pos.get('final_target')
                pos['targets'] = m_pos.get('targets', [])
                logger.info(f"Enriched {sym}: SL={pos['current_sl']}, TGT={pos['final_target']} (Keys: Strict={key_strict in monitor_map}, Relaxed={key_relaxed in monitor_map})")
            else:
                pos['current_sl'] = '-'
                pos['final_target'] = '-'
                pos['targets'] = []
                
    except Exception as e:
        logger.error(f"Error enriching positions with monitor data: {e}")
    
    return positions


def enrich_positions_with_ltp(positions, login_username, auth_token, broker):
    """Enrich positions with real-time LTP data"""
    try:
        if not positions:
            return positions
            
        # Collect unique symbols
        unique_symbols = {} # (symbol, exchange) -> None
        for position in positions:
            s = position.get('symbol')
            e = position.get('exchange')
            if s and e:
                unique_symbols[(s, e)] = None
        
        symbols_to_fetch = [{'symbol': s, 'exchange': e} for s, e in unique_symbols.keys()]
        
        if symbols_to_fetch:
            from services.quotes_service import get_multiquotes
            from database.settings_db import get_analyze_mode
            from database.auth_db import get_api_key_for_tradingview
            
            if get_analyze_mode():
                api_key = get_api_key_for_tradingview(login_username)
                success, q_resp, _ = get_multiquotes(symbols=symbols_to_fetch, api_key=api_key)
            else:
                success, q_resp, _ = get_multiquotes(symbols=symbols_to_fetch, auth_token=auth_token, broker=broker)
                
            if success and 'results' in q_resp:
                logger.info(f"Positions MTM: Multiquotes fetched {len(q_resp['results'])}/{len(symbols_to_fetch)} symbols")
                ltp_map = {} 
                for item in q_resp['results']:
                    val = None
                    if 'data' in item:
                        if 'ltp' in item['data']:
                            val = item['data']['ltp']
                        elif 'lp' in item['data']:
                            val = item['data']['lp']
                    elif 'ltp' in item:
                        val = item['ltp']
                    elif 'lp' in item:
                        val = item['lp']
                    
                    if val is not None:
                        k_sym = str(item.get('symbol', ''))
                        k_exc = str(item.get('exchange', ''))
                        ltp_map[(k_sym, k_exc)] = val
                        ltp_map[(k_sym.upper(), k_exc.upper())] = val

                for position in positions:
                    s = str(position.get('symbol'))
                    e = str(position.get('exchange'))
                    
                    # Try matching with different case combinations
                    found_val = None
                    if (s, e) in ltp_map: 
                        found_val = ltp_map[(s, e)]
                    elif (s.upper(), e.upper()) in ltp_map: 
                        found_val = ltp_map[(s.upper(), e.upper())]
                    
                    if found_val is not None:
                        position['ltp'] = found_val
                    else:
                        position['ltp'] = '-'
            else:
                # Set defaults on failure
                for position in positions:
                    position['ltp'] = '-'
        else:
            for position in positions:
                position['ltp'] = '-'

    except Exception as e:
        logger.error(f"Error enriching positions with LTP: {e}", exc_info=True)
        
    return positions

def enrich_orders_with_ltp(orders, login_username, auth_token, broker):
    """Enrich orders with LTP data"""
    try:
        if not orders:
            return orders
            
        # Collect unique symbols
        unique_symbols = {} # (symbol, exchange) -> None
        for order in orders:
            s = order.get('symbol')
            e = order.get('exchange')
            if s and e:
                unique_symbols[(s, e)] = None
        
        symbols_to_fetch = [{'symbol': s, 'exchange': e} for s, e in unique_symbols.keys()]
        
        if symbols_to_fetch:
            if get_analyze_mode():
                api_key = get_api_key_for_tradingview(login_username)
                success, q_resp, _ = get_multiquotes(symbols=symbols_to_fetch, api_key=api_key)
            else:
                success, q_resp, _ = get_multiquotes(symbols=symbols_to_fetch, auth_token=auth_token, broker=broker)
                
            if success and 'results' in q_resp:
                logger.info(f"LTP Enrichment: Got results for {len(q_resp['results'])} symbols")
                ltp_map = {} 
                for item in q_resp['results']:
                    # Log the item structure for debugging
                    logger.info(f"LTP Item: {item}")
                    
                    val = None
                    if 'data' in item:
                        if 'ltp' in item['data']:
                            val = item['data']['ltp']
                        elif 'lp' in item['data']:
                            val = item['data']['lp']
                    elif 'ltp' in item:
                        val = item['ltp']
                    elif 'lp' in item:
                        val = item['lp']
                    
                    if val is not None:
                        # Ensure keys match order data format (str)
                        k_sym = str(item.get('symbol', ''))
                        k_exc = str(item.get('exchange', ''))
                        ltp_map[(k_sym, k_exc)] = val
                        # Also try alternate key formats if needed
                        ltp_map[(k_sym, k_exc.upper())] = val
                        ltp_map[(k_sym.upper(), k_exc)] = val
                        ltp_map[(k_sym.upper(), k_exc.upper())] = val

                logger.info(f"LTP Map keys: {list(ltp_map.keys())}")

                for order in orders:
                    s = str(order.get('symbol'))
                    e = str(order.get('exchange'))
                    key = (s, e)
                    
                    # Try exhaustive matching
                    found_val = None
                    if (s, e) in ltp_map: found_val = ltp_map[(s, e)]
                    elif (s, e.upper()) in ltp_map: found_val = ltp_map[(s, e.upper())]
                    elif (s.upper(), e) in ltp_map: found_val = ltp_map[(s.upper(), e)]
                    elif (s.upper(), e.upper()) in ltp_map: found_val = ltp_map[(s.upper(), e.upper())]
                    
                    if found_val is not None:
                        order['ltp'] = found_val
                    else:
                        order['ltp'] = '-'
                        logger.warning(f"LTP Missing for order: {s} ({e}) - Available keys: {list(ltp_map.keys())[:5]}...")
            else:
                logger.warning(f"Failed to fetch multiquotes for orderbook ltp enrichment: {q_resp}")
                # Set defaults
                for order in orders:
                     order['ltp'] = '-'
        else:
             logger.info("No symbols to fetch for LTP enrichment")
             for order in orders:
                 order['ltp'] = '-'

    except Exception as e:
        logger.error(f"Error enriching orderbook with LTP: {e}", exc_info=True)
        
    return orders

def dynamic_import(broker, module_name, function_names):
    module_functions = {}
    try:
        # Import the module based on the broker name
        module = import_module(f'broker.{broker}.{module_name}')
        for name in function_names:
            module_functions[name] = getattr(module, name)
        return module_functions
    except (ImportError, AttributeError) as e:
        logger.error(f"Error importing functions {function_names} from {module_name} for broker {broker}: {e}")

        return None
def generate_orderbook_csv(order_data):
    """Generate CSV file from orderbook data"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write headers matching the terminal display
    headers = ['Trading Symbol', 'Exchange', 'Transaction Type', 'Quantity', 'Price', 
              'Trigger Price', 'Order Type', 'Product Type', 'Order ID', 'Status', 'Time']
    writer.writerow(headers)
    
    # Write data in the same order as the headers
    for order in order_data:
        row = [
            order.get('symbol', ''),
            order.get('exchange', ''),
            order.get('action', ''),
            order.get('quantity', ''),
            order.get('price', ''),
            order.get('trigger_price', ''),
            order.get('pricetype', ''),
            order.get('product', ''),
            order.get('orderid', ''),
            order.get('order_status', ''),
            order.get('timestamp', '')
        ]
        writer.writerow(row)
    
    return output.getvalue()

def generate_tradebook_csv(trade_data):
    """Generate CSV file from tradebook data"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write headers
    headers = ['Trading Symbol', 'Exchange', 'Product Type', 'Transaction Type', 'Fill Size', 
              'Fill Price', 'Trade Value', 'Order ID', 'Fill Time']
    writer.writerow(headers)
    
    # Write data
    for trade in trade_data:
        row = [
            trade.get('symbol', ''),
            trade.get('exchange', ''),
            trade.get('product', ''),
            trade.get('action', ''),
            trade.get('quantity', ''),
            trade.get('average_price', ''),
            trade.get('trade_value', ''),
            trade.get('orderid', ''),
            trade.get('timestamp', '')
        ]
        writer.writerow(row)
    
    return output.getvalue()

def generate_positions_csv(positions_data):
    """Generate CSV file from positions data"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write headers - updated to match terminal output exactly
    headers = ['Symbol', 'Exchange', 'Product Type', 'Net Qty', 'Avg Price', 'LTP', 'P&L']
    writer.writerow(headers)
    
    # Write data
    for position in positions_data:
        row = [
            position.get('symbol', ''),
            position.get('exchange', ''),
            position.get('product', ''),
            position.get('quantity', ''),
            position.get('average_price', ''),
            position.get('ltp', ''),
            position.get('pnl', '')
        ]
        writer.writerow(row)
    
    return output.getvalue()

@orders_bp.route('/orderbook')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def orderbook():
    login_username = session['user']
    auth_token = get_auth_token(login_username)

    if auth_token is None:
        logger.warning(f"No auth token found for user {login_username}")
        return redirect(url_for('auth.logout'))

    broker = session.get('broker')
    if not broker:
        logger.error("Broker not set in session")
        return "Broker not set in session", 400

    # Check if in analyze mode and route accordingly
    if get_analyze_mode():
        # Get API key for sandbox mode
        api_key = get_api_key_for_tradingview(login_username)
        if api_key:
            success, response, status_code = get_orderbook(api_key=api_key)
        else:
            logger.error("No API key found for analyze mode")
            return "API key required for analyze mode", 400
    else:
        # Use live broker
        success, response, status_code = get_orderbook(auth_token=auth_token, broker=broker)

    if not success:
        logger.error(f"Failed to get orderbook data: {response.get('message', 'Unknown error')}")
        if status_code == 404:
            return "Failed to import broker module", 500
        return redirect(url_for('auth.logout'))

    data = response.get('data', {})
    order_data = data.get('orders', [])
    order_data = enrich_orders_with_ltp(order_data, login_username, auth_token, broker)
    order_stats = data.get('statistics', {})

    return render_template('orderbook.html', order_data=order_data, order_stats=order_stats)

@orders_bp.route('/tradebook')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def tradebook():
    login_username = session['user']
    auth_token = get_auth_token(login_username)

    if auth_token is None:
        logger.warning(f"No auth token found for user {login_username}")
        return redirect(url_for('auth.logout'))

    broker = session.get('broker')
    if not broker:
        logger.error("Broker not set in session")
        return "Broker not set in session", 400

    # Check if in analyze mode and route accordingly
    if get_analyze_mode():
        # Get API key for sandbox mode
        api_key = get_api_key_for_tradingview(login_username)
        if api_key:
            success, response, status_code = get_tradebook(api_key=api_key)
        else:
            logger.error("No API key found for analyze mode")
            return "API key required for analyze mode", 400
    else:
        # Use live broker
        success, response, status_code = get_tradebook(auth_token=auth_token, broker=broker)

    if not success:
        logger.error(f"Failed to get tradebook data: {response.get('message', 'Unknown error')}")
        if status_code == 404:
            return "Failed to import broker module", 500
        return redirect(url_for('auth.logout'))

    tradebook_data = response.get('data', [])
    # tradebook_data = enrich_trades_with_ltp(tradebook_data, login_username, auth_token, broker) # Removed

    return render_template('tradebook.html', tradebook_data=tradebook_data)

@orders_bp.route('/positions')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def positions():
    login_username = session['user']
    auth_token = get_auth_token(login_username)

    if auth_token is None:
        logger.warning(f"No auth token found for user {login_username}")
        return redirect(url_for('auth.logout'))

    broker = session.get('broker')
    if not broker:
        logger.error("Broker not set in session")
        return "Broker not set in session", 400

    # Check if in analyze mode and route accordingly
    if get_analyze_mode():
        # Get API key for sandbox mode
        api_key = get_api_key_for_tradingview(login_username)
        if api_key:
            success, response, status_code = get_positionbook(api_key=api_key)
        else:
            logger.error("No API key found for analyze mode")
            return "API key required for analyze mode", 400
    else:
        # Use live broker
        success, response, status_code = get_positionbook(auth_token=auth_token, broker=broker)

    if not success:
        logger.error(f"Failed to get positions data: {response.get('message', 'Unknown error')}")
        if status_code == 404:
            return "Failed to import broker module", 500
        return redirect(url_for('auth.logout'))

    positions_data = response.get('data', [])
    positions_data = enrich_positions_with_monitor(positions_data)

    return render_template('positions.html', positions_data=positions_data)

@orders_bp.route('/holdings')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def holdings():
    login_username = session['user']
    auth_token = get_auth_token(login_username)

    if auth_token is None:
        logger.warning(f"No auth token found for user {login_username}")
        return redirect(url_for('auth.logout'))

    broker = session.get('broker')
    if not broker:
        logger.error("Broker not set in session")
        return "Broker not set in session", 400

    # Check if in analyze mode and route accordingly
    if get_analyze_mode():
        # Get API key for sandbox mode
        api_key = get_api_key_for_tradingview(login_username)
        if api_key:
            success, response, status_code = get_holdings(api_key=api_key)
        else:
            logger.error("No API key found for analyze mode")
            return "API key required for analyze mode", 400
    else:
        # Use live broker
        success, response, status_code = get_holdings(auth_token=auth_token, broker=broker)

    if not success:
        logger.error(f"Failed to get holdings data: {response.get('message', 'Unknown error')}")
        if status_code == 404:
            return "Failed to import broker module", 500
        return redirect(url_for('auth.logout'))

    data = response.get('data', {})
    holdings_data = data.get('holdings', [])
    portfolio_stats = data.get('statistics', {})

    return render_template('holdings.html', holdings_data=holdings_data, portfolio_stats=portfolio_stats)

@orders_bp.route('/orderbook/export')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def export_orderbook():
    try:
        login_username = session['user']
        auth_token = get_auth_token(login_username)
        broker = session.get('broker')

        if auth_token is None:
            logger.warning(f"No auth token found for user {login_username}")
            return redirect(url_for('auth.logout'))

        # Check if in analyze mode and route accordingly
        if get_analyze_mode():
            # Get API key for sandbox mode
            api_key = get_api_key_for_tradingview(login_username)
            if api_key:
                success, response, status_code = get_orderbook(api_key=api_key)
                if not success:
                    logger.error(f"Failed to get orderbook data in analyze mode")
                    return "Error getting orderbook data", 500
                data = response.get('data', {})
                order_data = data.get('orders', [])
            else:
                logger.error("No API key found for analyze mode")
                return "API key required for analyze mode", 400
        else:
            # Use live broker
            if not broker:
                logger.error("Broker not set in session")
                return "Broker not set in session", 400

            api_funcs = dynamic_import(broker, 'api.order_api', ['get_order_book'])
            mapping_funcs = dynamic_import(broker, 'mapping.order_data', ['map_order_data', 'transform_order_data'])

            if not api_funcs or not mapping_funcs:
                logger.error(f"Error loading broker-specific modules for {broker}")
                return "Error loading broker-specific modules", 500

            order_data = api_funcs['get_order_book'](auth_token)
            if 'status' in order_data and order_data['status'] == 'error':
                logger.error("Error in order data response")
                return redirect(url_for('auth.logout'))

            order_data = mapping_funcs['map_order_data'](order_data=order_data)
            order_data = mapping_funcs['transform_order_data'](order_data)

        csv_data = generate_orderbook_csv(order_data)
        return Response(
            csv_data,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=orderbook.csv'}
        )
    except Exception as e:
        logger.error(f"Error exporting orderbook: {str(e)}")
        return "Error exporting orderbook", 500

@orders_bp.route('/tradebook/export')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def export_tradebook():
    try:
        login_username = session['user']
        auth_token = get_auth_token(login_username)
        broker = session.get('broker')

        if auth_token is None:
            logger.warning(f"No auth token found for user {login_username}")
            return redirect(url_for('auth.logout'))

        # Check if in analyze mode and route accordingly
        if get_analyze_mode():
            # Get API key for sandbox mode
            api_key = get_api_key_for_tradingview(login_username)
            if api_key:
                success, response, status_code = get_tradebook(api_key=api_key)
                if not success:
                    logger.error(f"Failed to get tradebook data in analyze mode")
                    return "Error getting tradebook data", 500
                tradebook_data = response.get('data', [])
            else:
                logger.error("No API key found for analyze mode")
                return "API key required for analyze mode", 400
        else:
            # Use live broker
            if not broker:
                logger.error("Broker not set in session")
                return "Broker not set in session", 400

            api_funcs = dynamic_import(broker, 'api.order_api', ['get_trade_book'])
            mapping_funcs = dynamic_import(broker, 'mapping.order_data', ['map_trade_data', 'transform_tradebook_data'])

            if not api_funcs or not mapping_funcs:
                logger.error(f"Error loading broker-specific modules for {broker}")
                return "Error loading broker-specific modules", 500

            tradebook_data = api_funcs['get_trade_book'](auth_token)
            if 'status' in tradebook_data and tradebook_data['status'] == 'error':
                logger.error("Error in tradebook data response")
                return redirect(url_for('auth.logout'))

            tradebook_data = mapping_funcs['map_trade_data'](tradebook_data)
            tradebook_data = mapping_funcs['transform_tradebook_data'](tradebook_data)

        csv_data = generate_tradebook_csv(tradebook_data)
        return Response(
            csv_data,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=tradebook.csv'}
        )
    except Exception as e:
        logger.error(f"Error exporting tradebook: {str(e)}")
        return "Error exporting tradebook", 500

@orders_bp.route('/positions/export')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def export_positions():
    try:
        login_username = session['user']
        auth_token = get_auth_token(login_username)
        broker = session.get('broker')

        if auth_token is None:
            logger.warning(f"No auth token found for user {login_username}")
            return redirect(url_for('auth.logout'))

        # Check if in analyze mode and route accordingly
        if get_analyze_mode():
            # Get API key for sandbox mode
            api_key = get_api_key_for_tradingview(login_username)
            if api_key:
                success, response, status_code = get_positionbook(api_key=api_key)
                if not success:
                    logger.error(f"Failed to get positions data in analyze mode")
                    return "Error getting positions data", 500
                positions_data = response.get('data', [])
            else:
                logger.error("No API key found for analyze mode")
                return "API key required for analyze mode", 400
        else:
            # Use live broker
            if not broker:
                logger.error("Broker not set in session")
                return "Broker not set in session", 400

            api_funcs = dynamic_import(broker, 'api.order_api', ['get_positions'])
            mapping_funcs = dynamic_import(broker, 'mapping.order_data', [
                'map_position_data', 'transform_positions_data'
            ])

            if not api_funcs or not mapping_funcs:
                logger.error(f"Error loading broker-specific modules for {broker}")
                return "Error loading broker-specific modules", 500

            positions_data = api_funcs['get_positions'](auth_token)
            if 'status' in positions_data and positions_data['status'] == 'error':
                logger.error("Error in positions data response")
                return redirect(url_for('auth.logout'))

            positions_data = mapping_funcs['map_position_data'](positions_data)
            positions_data = mapping_funcs['transform_positions_data'](positions_data)

        csv_data = generate_positions_csv(positions_data)
        return Response(
            csv_data,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=positions.csv'}
        )
    except Exception as e:
        logger.error(f"Error exporting positions: {str(e)}")
        return "Error exporting positions", 500

@orders_bp.route('/close_position', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def close_position():
    """Close a specific position - uses broker API in live mode, placesmartorder service in analyze mode"""
    try:
        # Get data from request
        data = request.json
        symbol = data.get('symbol')
        exchange = data.get('exchange')
        product = data.get('product')

        if not all([symbol, exchange, product]):
            return jsonify({
                'status': 'error',
                'message': 'Missing required parameters (symbol, exchange, product)'
            }), 400

        # Get auth token from session
        login_username = session['user']
        auth_token = get_auth_token(login_username)
        broker_name = session.get('broker')

        # Check if in analyze mode
        if get_analyze_mode():
            # In analyze mode, use placesmartorder service with quantity=0 and position_size=0
            api_key = get_api_key_for_tradingview(login_username)

            if not api_key:
                return jsonify({
                    'status': 'error',
                    'message': 'API key not found for analyze mode'
                }), 401

            # Prepare order data for placesmartorder service (without apikey in data)
            order_data = {
                "strategy": "UI Exit Position",
                "exchange": exchange,
                "symbol": symbol,
                "action": "BUY",  # Will be determined by smart order logic
                "product_type": product,
                "pricetype": "MARKET",
                "quantity": "0",
                "price": "0",
                "trigger_price": "0",
                "disclosed_quantity": "0",
                "position_size": "0"  # Setting to 0 to close the position
            }

            # Use placesmartorder service for analyze mode
            from services.place_smart_order_service import place_smart_order

            # Pass api_key as a separate parameter for analyze mode
            success, response_data, status_code = place_smart_order(
                order_data=order_data,
                api_key=api_key
            )
            return jsonify(response_data), status_code

        # Live mode - continue with existing logic
        if not auth_token or not broker_name:
            return jsonify({
                'status': 'error',
                'message': 'Authentication error'
            }), 401

        # Dynamically import broker-specific modules for API
        api_funcs = dynamic_import(broker_name, 'api.order_api', ['place_smartorder_api', 'get_open_position'])

        if not api_funcs:
            logger.error(f"Error loading broker-specific modules for {broker_name}")
            return jsonify({
                'status': 'error',
                'message': 'Error loading broker modules'
            }), 500

        # Get the functions we need
        place_smartorder_api = api_funcs['place_smartorder_api']

        # Prepare order data for direct broker API call
        order_data = {
            "strategy": "UI Exit Position",
            "exchange": exchange,
            "symbol": symbol,
            "action": "BUY",  # Will be determined by the smart order API based on current position
            "product": product,
            "pricetype": "MARKET",
            "quantity": "0",
            "price": "0",
            "trigger_price": "0",
            "disclosed_quantity": "0",
            "position_size": "0"  # Setting to 0 to close the position
        }

        # Call the broker API directly
        res, response, orderid = place_smartorder_api(order_data, auth_token)
        
        # Format the response based on presence of orderid and broker's response
        if orderid:
            response_data = {
                'status': 'success',
                'message': response.get('message') if response and 'message' in response else 'Position close order placed successfully.',
                'orderid': orderid
            }
            status_code = 200
        else:
            # No orderid, definite error
            response_data = {
                'status': 'error',
                'message': response.get('message') if response and 'message' in response else 'Failed to close position (broker did not return order ID).'
            }
            if res and hasattr(res, 'status') and isinstance(res.status, int) and res.status >= 400:
                status_code = res.status  # Use broker's HTTP error code if available
            else:
                status_code = 400 # Default to Bad Request
        
        return jsonify(response_data), status_code
        
    except Exception as e:
        logger.error(f"Error in close_position endpoint: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'An error occurred: {str(e)}'
        }), 500

@orders_bp.route('/close_all_positions', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def close_all_positions():
    """Close all open positions using the broker API"""
    try:
        # Get auth token from session
        login_username = session['user']
        auth_token = get_auth_token(login_username)
        broker_name = session.get('broker')

        if not auth_token or not broker_name:
            return jsonify({
                'status': 'error',
                'message': 'Authentication error'
            }), 401

        # Import necessary functions
        from services.close_position_service import close_position
        from database.auth_db import get_api_key_for_tradingview
        from database.settings_db import get_analyze_mode

        # Get API key for analyze mode
        api_key = None
        if get_analyze_mode():
            api_key = get_api_key_for_tradingview(login_username)

        # Call the service with appropriate parameters
        success, response_data, status_code = close_position(
            position_data={},
            api_key=api_key,
            auth_token=auth_token,
            broker=broker_name
        )

        # Format the response for UI
        if success and status_code == 200:
            return jsonify({
                'status': 'success',
                'message': response_data.get('message', 'All Open Positions Squared Off')
            }), 200
        else:
            return jsonify(response_data), status_code
        
    except Exception as e:
        logger.error(f"Error in close_all_positions endpoint: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'An error occurred: {str(e)}'
        }), 500

@orders_bp.route('/cancel_all_orders', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def cancel_all_orders_ui():
    """Cancel all open orders using the broker API from UI"""
    try:
        # Get auth token from session
        login_username = session['user']
        auth_token = get_auth_token(login_username)
        broker_name = session.get('broker')

        if not auth_token or not broker_name:
            return jsonify({
                'status': 'error',
                'message': 'Authentication error'
            }), 401

        # Import necessary functions
        from services.cancel_all_order_service import cancel_all_orders
        from database.auth_db import get_api_key_for_tradingview
        from database.settings_db import get_analyze_mode

        # Get API key for analyze mode
        api_key = None
        if get_analyze_mode():
            api_key = get_api_key_for_tradingview(login_username)

        # Call the service with appropriate parameters
        success, response_data, status_code = cancel_all_orders(
            order_data={},
            api_key=api_key,
            auth_token=auth_token,
            broker=broker_name
        )
        
        # Format the response for UI
        if success and status_code == 200:
            canceled_count = len(response_data.get('canceled_orders', []))
            failed_count = len(response_data.get('failed_cancellations', []))
            
            if canceled_count > 0 or failed_count == 0:
                message = f'Successfully canceled {canceled_count} orders'
                if failed_count > 0:
                    message += f' (Failed to cancel {failed_count} orders)'
                return jsonify({
                    'status': 'success',
                    'message': message,
                    'canceled_orders': response_data.get('canceled_orders', []),
                    'failed_cancellations': response_data.get('failed_cancellations', [])
                }), 200
            else:
                return jsonify({
                    'status': 'info',
                    'message': 'No open orders to cancel'
                }), 200
        else:
            return jsonify(response_data), status_code
        
    except Exception as e:
        logger.error(f"Error in cancel_all_orders_ui endpoint: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'An error occurred: {str(e)}'
        }), 500

@orders_bp.route('/action-center')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def action_center():
    """
    Action Center - Manage pending semi-automated orders
    Similar to orderbook but for pending approval orders
    """
    login_username = session['user']

    # Get filter from query params
    status_filter = request.args.get('status', 'pending')  # pending, approved, rejected, all

    # Get action center data
    from services.action_center_service import get_action_center_data

    if status_filter == 'all':
        success, response, status_code = get_action_center_data(login_username, status_filter=None)
    else:
        success, response, status_code = get_action_center_data(login_username, status_filter=status_filter)

    if not success:
        logger.error(f"Failed to get action center data: {response.get('message', 'Unknown error')}")
        return render_template('action_center.html',
                             order_data=[],
                             order_stats={},
                             current_filter=status_filter,
                             login_username=login_username)

    data = response.get('data', {})
    order_data = data.get('orders', [])
    order_stats = data.get('statistics', {})

    return render_template('action_center.html',
                         order_data=order_data,
                         order_stats=order_stats,
                         current_filter=status_filter,
                         login_username=login_username)

@orders_bp.route('/action-center/approve/<int:order_id>', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def approve_pending_order_route(order_id):
    """Approve a pending order and execute it"""
    login_username = session['user']

    from database.action_center_db import approve_pending_order
    from services.pending_order_execution_service import execute_approved_order
    from extensions import socketio

    # Approve the order
    success = approve_pending_order(order_id, approved_by=login_username, user_id=login_username)

    if success:
        # Execute the order
        exec_success, response_data, status_code = execute_approved_order(order_id)

        # Emit socket event to notify about order approval
        socketio.emit('pending_order_updated', {
            'action': 'approved',
            'order_id': order_id,
            'user_id': login_username
        })

        if exec_success:
            return jsonify({
                'status': 'success',
                'message': 'Order approved and executed successfully',
                'broker_order_id': response_data.get('orderid')
            })
        else:
            return jsonify({
                'status': 'warning',
                'message': 'Order approved but execution failed',
                'error': response_data.get('message')
            }), status_code
    else:
        return jsonify({'status': 'error', 'message': 'Failed to approve order'}), 400

@orders_bp.route('/action-center/reject/<int:order_id>', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def reject_pending_order_route(order_id):
    """Reject a pending order"""
    login_username = session['user']
    data = request.json
    reason = data.get('reason', 'No reason provided')

    from database.action_center_db import reject_pending_order
    from extensions import socketio

    success = reject_pending_order(order_id, reason=reason, rejected_by=login_username, user_id=login_username)

    if success:
        # Emit socket event to notify about order rejection
        socketio.emit('pending_order_updated', {
            'action': 'rejected',
            'order_id': order_id,
            'user_id': login_username
        })

        return jsonify({
            'status': 'success',
            'message': 'Order rejected successfully'
        })
    else:
        return jsonify({'status': 'error', 'message': 'Failed to reject order'}), 400

@orders_bp.route('/action-center/delete/<int:order_id>', methods=['DELETE'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def delete_pending_order_route(order_id):
    """Delete a pending order (only if not pending)"""
    login_username = session['user']

    from database.action_center_db import delete_pending_order
    from extensions import socketio

    success = delete_pending_order(order_id, user_id=login_username)

    if success:
        # Emit socket event to notify about order deletion
        socketio.emit('pending_order_updated', {
            'action': 'deleted',
            'order_id': order_id,
            'user_id': login_username
        })

        return jsonify({'status': 'success', 'message': 'Order deleted successfully'})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to delete order'}), 400

@orders_bp.route('/action-center/count')
@check_session_validity
def action_center_count():
    """Get count of pending orders for badge"""
    login_username = session['user']

    from database.action_center_db import get_pending_count

    count = get_pending_count(login_username)

    return jsonify({'count': count})

@orders_bp.route('/action-center/approve-all', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def approve_all_pending_orders():
    """Approve and execute all pending orders"""
    login_username = session['user']

    from database.action_center_db import get_pending_orders, approve_pending_order
    from services.pending_order_execution_service import execute_approved_order
    from extensions import socketio

    # Get all pending orders for this user
    pending_orders = get_pending_orders(login_username, status='pending')

    if not pending_orders:
        return jsonify({
            'status': 'info',
            'message': 'No pending orders to approve'
        }), 200

    # Track results
    approved_count = 0
    executed_count = 0
    failed_executions = []

    # Approve and execute each order
    for order in pending_orders:
        # Approve the order
        success = approve_pending_order(order.id, approved_by=login_username)

        if success:
            approved_count += 1

            # Execute the order
            exec_success, response_data, status_code = execute_approved_order(order.id)

            if exec_success:
                executed_count += 1
            else:
                failed_executions.append({
                    'order_id': order.id,
                    'error': response_data.get('message', 'Unknown error')
                })

    # Emit socket event to notify about batch approval
    socketio.emit('pending_order_updated', {
        'action': 'batch_approved',
        'user_id': login_username,
        'count': approved_count
    })

    # Prepare response message
    if approved_count == executed_count:
        message = f'Successfully approved and executed all {approved_count} orders'
        status = 'success'
    elif executed_count > 0:
        message = f'Approved {approved_count} orders. {executed_count} executed successfully, {len(failed_executions)} failed'
        status = 'warning'
    else:
        message = f'Approved {approved_count} orders but all executions failed'
        status = 'error'

    return jsonify({
        'status': status,
        'message': message,
        'approved_count': approved_count,
        'executed_count': executed_count,
        'failed_executions': failed_executions
    }), 200

@orders_bp.route('/api/update_position', methods=['POST'])
@check_session_validity
def update_position_api():
    """API endpoint to update position SL/Target"""
    try:
        data = request.json
        symbol = data.get('symbol')
        exchange = data.get('exchange')
        product = data.get('product')
        new_sl = data.get('sl')
        new_target = data.get('target')

        if not all([symbol, exchange, product]):
            return jsonify({'status': 'error', 'message': 'Missing symbol, exchange or product'}), 400

        # Find the order_id for this position
        active_monitored = position_monitor.get_active_positions()
        target_order_id = None
        
        # DEBUG: Log what we're searching for
        logger.info(f"🔍 Searching for position: symbol={symbol}, exchange={exchange}, product={product}")
        logger.info(f"📊 Monitored positions count: {len(active_monitored)}")
        
        for pid, pdata in active_monitored.items():
            logger.info(f"   Checking {pid}: symbol={pdata.get('symbol')}, exchange={pdata.get('exchange')}, product={pdata.get('product')}")
            if (pdata.get('symbol') == symbol and 
                pdata.get('exchange') == exchange and 
                pdata.get('product') == product):
                target_order_id = pid
                logger.info(f"✅ MATCH FOUND: {pid}")
                break
        
        if not target_order_id:
            logger.error(f"❌ Position not found in monitor. Searched for: {symbol}/{exchange}/{product}")
            logger.error(f"Available positions: {[(p.get('symbol'), p.get('exchange'), p.get('product')) for p in active_monitored.values()]}")
            return jsonify({'status': 'error', 'message': 'Position not found in monitor'}), 404

        updates = []
        
        # Update SL
        if new_sl is not None:
            try:
                sl_val = float(new_sl)
                if position_monitor.update_sl(target_order_id, sl_val):
                    updates.append(f"SL updated to {sl_val}")
            except ValueError:
                return jsonify({'status': 'error', 'message': 'Invalid SL value'}), 400

        # Update Target(s)
        if new_target is not None:
             # Backward compatibility for single target
             try:
                tgt_val = float(new_target)
                if position_monitor.update_target(target_order_id, tgt_val):
                    updates.append(f"Target updated to {tgt_val}")
             except ValueError:
                return jsonify({'status': 'error', 'message': 'Invalid Target value'}), 400
        
        # New: Update Targets List (T1, T2, T3)
        new_targets = data.get('targets')
        if new_targets is not None and isinstance(new_targets, list):
            try:
                # Filter valid numbers
                valid_targets = [float(t) for t in new_targets if t is not None and t != '']
                if position_monitor.update_targets(target_order_id, valid_targets):
                     updates.append(f"Targets updated to {valid_targets}")
                     
                     # Also update final_target (max of targets)
                     if valid_targets:
                         final = max(valid_targets)
                         position_monitor.update_target(target_order_id, final)
            except Exception as e:
                logger.error(f"Error updating targets list: {e}")
                return jsonify({'status': 'error', 'message': 'Invalid Targets list'}), 400

        if not updates:
             return jsonify({'status': 'error', 'message': 'No valid updates provided'}), 400

        return jsonify({'status': 'success', 'message': ', '.join(updates)})

    except Exception as e:
        logger.error(f"Error updating position: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
