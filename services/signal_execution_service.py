"""
Signal Auto-Execution Service

Connects Telegram signals to broker order placement with safety features:
- Enable/Disable toggle
- Confidence threshold
- Duplicate signal filtering
- Sandbox mode support
- Order validation
"""

import os
import asyncio
from typing import Dict, Optional
from datetime import datetime, timedelta
from collections import defaultdict
from utils.logging import get_logger
from database.symbol import SymToken, db_session
from sqlalchemy import and_, func
from sqlalchemy import and_, func
from sqlalchemy import and_, func
from datetime import datetime
from database.auth_db import get_auth_token_dbquery, decrypt_token, get_api_key_for_tradingview
from services.quotes_service import get_quotes

logger = get_logger(__name__)


class SignalExecutionService:
    """Auto-execute trading signals with safety controls"""
    
    def __init__(self):
        # Safety toggle
        self.enabled = os.getenv("AUTO_EXECUTE_SIGNALS", "false").lower() == "true"
        
        # Confidence threshold (0.0 to 1.0)
        self.confidence_threshold = float(os.getenv("SIGNAL_CONFIDENCE_THRESHOLD", "0.7"))
        
        # Duplicate signal filtering (in seconds)
        self.duplicate_window = 5  # Reduced to 5s for testing (default 60)
        
        # Track recent signals to prevent duplicates
        self.recent_signals = defaultdict(list)  # {channel: [(signal_hash, timestamp), ...]}
        
        # Execution stats
        self.stats = {
            'total_signals': 0,
            'executed': 0,
            'skipped_low_confidence': 0,
            'skipped_duplicate': 0,
            'skipped_disabled': 0,
            'failed': 0
        }
        
        logger.info(f"Signal Execution Service initialized - Enabled: {self.enabled}, Threshold: {self.confidence_threshold}")
    
    def enable(self):
        """Enable auto-execution"""
        self.enabled = True
        logger.warning("⚠️ AUTO-EXECUTION ENABLED - Signals will place real orders!")
    
    def disable(self):
        """Disable auto-execution"""
        self.enabled = False
        logger.info("Auto-execution disabled")
    
    def _generate_signal_hash(self, signal_data: Dict) -> str:
        """Generate unique hash for signal to detect duplicates"""
        # Use action + symbol + strike + option_type as identifier
        parts = [
            str(signal_data.get('action', '')),
            str(signal_data.get('symbol', '')),
            str(signal_data.get('strike', '')),
            str(signal_data.get('option_type', ''))
        ]
        return '|'.join(parts).upper()
    
    def _is_duplicate(self, channel: str, signal_data: Dict) -> bool:
        """Check if signal is duplicate within time window"""
        signal_hash = self._generate_signal_hash(signal_data)
        now = datetime.now()
        
        # Clean old signals
        self.recent_signals[channel] = [
            (h, t) for h, t in self.recent_signals[channel]
            if (now - t).total_seconds() < self.duplicate_window
        ]
        
        # Check for duplicate
        for existing_hash, timestamp in self.recent_signals[channel]:
            if existing_hash == signal_hash:
                time_diff = (now - timestamp).total_seconds()
                logger.debug(f"Duplicate signal detected (seen {time_diff:.0f}s ago): {signal_hash}")
                return True
        
        # Add this signal to recent list
        self.recent_signals[channel].append((signal_hash, now))
        return False
    
    def _validate_signal(self, signal_data: Dict) -> tuple[bool, Optional[str]]:
        """
        Validate if signal has minimum required fields
        
        Returns:
            (is_valid, error_message)
        """
        # Minimum required: action and symbol
        if not signal_data.get('action'):
            return False, "Missing 'action' (BUY/SELL)"
        
        if not signal_data.get('symbol'):
            return False, "Missing 'symbol'"
        
        # Mandatory SL and Target check
        # Update: SL is now optional (Auto-calculated if missing)
        # if not signal_data.get('sl'):
        #      return False, "Missing Mandatory Stop Loss (SL)"
             
        if not (signal_data.get('tgt') or signal_data.get('targets')):
             return False, "Missing Mandatory Target"
             
        # If it looks like options, require strike and option_type
        if signal_data.get('strike') or signal_data.get('option_type'):
            if not signal_data.get('strike'):
                return False, "Options signal missing 'strike'"
            if not signal_data.get('option_type'):
                return False, "Options signal missing 'option_type' (CE/PE)"
        
        return True, None
    
    async def execute_signal(
        self, 
        signal_data: Dict, 
        channel: str, 
        raw_message: str,
        confidence: float = 1.0
    ) -> tuple[bool, str]:
        """
        Execute a parsed trading signal
        
        Args:
            signal_data: Parsed signal dictionary
            channel: Source channel name
            raw_message: Original message text
            confidence: Classifier confidence (0-1)
            
        Returns:
            (success: bool, message: str)
        """
        self.stats['total_signals'] += 1
        
        # Infer Action for Options if missing (Common Telegram pattern)
        if not signal_data.get('action') and signal_data.get('option_type') in ['CE', 'PE']:
             logger.info(f"Inferring BUY action for Option signal (missing action): {signal_data}")
             signal_data['action'] = 'BUY'

        # Auto-SL Calculation (User Rule: 10% of Entry if SL missing)
        if not signal_data.get('sl') and signal_data.get('price'):
            try:
                entry = float(signal_data['price'])
                action = signal_data.get('action', 'BUY').upper()
                sl_dist = entry * 0.10  # 10% Risk
                
                if action == 'BUY':
                    calc_sl = entry - sl_dist
                else:
                    calc_sl = entry + sl_dist
                    
                # Round to 1 decimal place or nearest tick (optional)
                calc_sl = round(calc_sl, 1)
                
                signal_data['sl'] = calc_sl
                logger.info(f"🛡️ Auto-SL Calculated: Entry {entry} -> Risk {sl_dist:.1f} (10%) -> SL {calc_sl}")
            except Exception as e:
                logger.error(f"Failed to auto-calculate SL: {e}")

        # Safety Check 1: Is auto-execution enabled?
        if not self.enabled:
            self.stats['skipped_disabled'] += 1
            logger.debug(f"Signal skipped - Auto-execution disabled")
            return False, "Auto-execution disabled"
        
        # Safety Check 2: Confidence threshold
        if confidence < self.confidence_threshold:
            self.stats['skipped_low_confidence'] += 1
            logger.debug(f"Signal skipped - Low confidence ({confidence:.2f} < {self.confidence_threshold})")
            return False, f"Low confidence ({confidence:.2f})"
        
        # Safety Check 3: Duplicate detection
        if self._is_duplicate(channel, signal_data):
            self.stats['skipped_duplicate'] += 1
            return False, "Duplicate signal"
        
        # Safety Check 4: Validate signal data
        is_valid, error = self._validate_signal(signal_data)
        if not is_valid:
            logger.warning(f"Invalid signal from {channel}: {error}")
            self.stats['failed'] += 1
            return False, f"Invalid: {error}"
        
        # Execute the order
        try:
            logger.info(f"🚀 EXECUTING SIGNAL from {channel} (confidence: {confidence:.2f}): {signal_data}")
            
            # Import order service
            from services.place_order_service import place_order
            
            # Convert signal data to OpenAlgo order format
            order_data = self._convert_signal_to_order(signal_data)
            
            # Place the order
            # Note: place_order() will use sandbox if ANALYZE_MODE is enabled
            # Retrieve auth token and broker for the default user
            # TODO: Make this configurable or multi-user aware
            username = 'aravind' 
            auth_obj = get_auth_token_dbquery(username)
            
            if not auth_obj or auth_obj.is_revoked:
                 logger.error(f"Cannot execute signal: No active session for user '{username}'")
                 return False, "No active broker session"
                 
            auth_token = decrypt_token(auth_obj.auth)
            broker = auth_obj.broker
            
            # Fetch API Key for validation
            api_key = get_api_key_for_tradingview(username)
            if api_key:
                order_data['apikey'] = api_key
            else:
                logger.warning(f"No API key found for {username} - Validation may fail")
            
            # Tag the order
            order_data['strategy'] = 'TelegramSignal'
            # order_data['tag'] = 'TELEGRAM' # Removed (Schema invalid)
            
            # Apply Trading Lots Multiplier (Global Setting)
            from database.settings_db import get_trading_lots
            lots_multiplier = get_trading_lots()
            if lots_multiplier > 1:
                original_qty = int(order_data.get('quantity', 1))
                new_qty = original_qty * lots_multiplier
                order_data['quantity'] = str(new_qty)
                logger.info(f"⚡ Lots Multiplier Applied: {original_qty} (Base) x {lots_multiplier} = {new_qty} Qty")
            
            # Place the order using internal auth (direct broker call)
            success, response, status_code = place_order(
                order_data=order_data,
                auth_token=auth_token,
                broker=broker
            )
            
            if success:
                self.stats['executed'] += 1
                order_id = response.get('orderid', 'N/A')
                logger.info(f"✅ Order placed successfully - ID: {order_id}")
                
                # Add position to monitoring for trailing SL
                try:
                    from services.position_monitor_service import position_monitor
                    
                    # Parse targets: Prefer 'targets' list from LLM, fallback to 'tgt'
                    targets = signal_data.get('targets', [])
                    if not targets:
                         # Fallback to single tgt if list is empty
                        single_tgt = signal_data.get('tgt')
                        if single_tgt:
                            targets = [single_tgt]
                    
                    # Convert to floats
                    target_floats = []
                    for t in targets:
                        try:
                            if t: target_floats.append(float(t))
                        except: pass
                    
                    # Auto-generate T2 and T3 if only one target provided (User Requirement)
                    if len(target_floats) == 1:
                        base_tgt = target_floats[0]
                        target_floats.append(base_tgt + 2.0) # T2
                        target_floats.append(base_tgt + 4.0) # T3
                        logger.info(f"Auto-generated targets: {target_floats}")
                    
                # CRITICAL FIX: Only add to position monitor if order is filled!
                # - MARKET orders fill instantly in sandbox, safe to add immediately
                # - SL/LIMIT orders are "open" until triggered - should NOT be monitored yet
                # 
                # User Bug Report: SL entry orders at 235.1 were being monitored before fill,
                # causing false SL exits at 229.95 that created unwanted SHORT positions
                
                # Check if this is a MARKET order (instant fill) or verify order filled
                should_add_to_monitor = False
                price_type = order_data.get('price_type', 'LIMIT').upper()
                
                if price_type == 'MARKET':
                    # MARKET orders execute instantly in sandbox - safe to monitor
                    should_add_to_monitor = True
                    logger.info(f"MARKET order filled instantly - adding to monitor")
                else:
                    # For SL/LIMIT orders, check if order actually filled
                    # Query the database to get current order status
                    from database.sandbox_db import SandboxOrders
                    filled_order = SandboxOrders.query.filter_by(orderid=order_id).first()
                    
                    if filled_order and filled_order.order_status == 'complete':
                        should_add_to_monitor = True
                        logger.info(f"{price_type} order confirmed filled - adding to monitor")
                    else:
                        should_add_to_monitor = False
                        logger.warning(f"⚠️ {price_type} order {order_id} NOT filled yet (Status: {filled_order.order_status if filled_order else 'Unknown'}) - SKIPPING monitor add. Will be added when order fills.")
                
                if should_add_to_monitor:
                    # Add to position monitor
                    position_monitor.add_position(
                        order_id=order_id,
                        symbol=order_data.get('symbol', ''),
                        exchange=order_data.get('exchange', ''),
                        action=signal_data.get('action', 'BUY'),
                        quantity=int(order_data.get('quantity', 1)), # Used final qty
                        entry_price=float(signal_data.get('price', 0)),
                        stop_loss=float(signal_data.get('sl', 0)) if signal_data.get('sl') else 0,
                        targets=target_floats,
                        signal_data=signal_data,
                        username=username, # Pass username
                        product=order_data.get('product', 'MIS') # Pass product
                    )
                    logger.info(f"Position added to monitoring - Targets: {target_floats}")
                else:
                    logger.info(f"Position NOT added to monitor (order pending) - will be added on fill callback")
                except Exception as e:
                    logger.error(f"Failed to add position to monitor: {e}")
                
                # Send Telegram alert if configured
                try:
                    from services.telegram_alert_service import telegram_alert_service
                    alert_msg = (
                        f"🎯 AUTO-EXECUTED\n"
                        f"Signal: {signal_data.get('action')} {signal_data.get('symbol')}\n"
                        f"Order ID: {order_id}\n"
                        f"Channel: {channel}"
                    )
                    await telegram_alert_service.send_alert(alert_msg)
                except Exception as e:
                    logger.debug(f"Telegram alert failed: {e}")
                
                return True, f"Order placed: {order_id}"
            else:
                self.stats['failed'] += 1
                error_msg = response.get('message', 'Unknown error')
                logger.error(f"❌ Order placement failed: {error_msg}")
                return False, f"Order failed: {error_msg}"
                
        except Exception as e:
            self.stats['failed'] += 1
            logger.error(f"Exception during signal execution: {e}", exc_info=True)
            return False, f"Exception: {str(e)}"
    
    def _convert_signal_to_order(self, signal_data: Dict) -> Dict:
        """
        Convert parsed signal to OpenAlgo order format
        
        Signal format:
            {action, symbol, strike, option_type, price, sl, tgt}
        
        OpenAlgo format:
            {symbol, exchange, action, quantity, price, product, pricetype, ...}
        """
        order = {}
        
        # Action: BUY/SELL
        order['action'] = signal_data.get('action', 'BUY').upper()
        
        # Symbol construction
        symbol = signal_data.get('symbol', '').upper()
        strike = signal_data.get('strike')
        option_type = signal_data.get('option_type', '').upper()
        
        # If options, construct full symbol
        if strike and option_type:
            # TODO: Need expiry date - for now use nearest weekly/monthly
            # This is a simplified version - you may need to enhance this
            order['symbol'] = symbol
            
            # Determine exchange for options
            if symbol in ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']:
                order['exchange'] = 'NFO'
            elif symbol in ['SENSEX', 'BANKEX']:
                order['exchange'] = 'BFO'
            elif symbol in ['CRUDEOIL', 'GOLD', 'SILVER', 'NATURALGAS', 'COPPER', 'ZINC']:
                order['exchange'] = 'MCX'
            else:
                 # Default logic for stocks defaults to NSE, assume NFO if options
                order['exchange'] = 'NFO'
                
            # Attempt to resolve the exact trading symbol
            expiry_tag = signal_data.get('expiry')
            resolved_symbol, resolved_lotsize = self._resolve_option_symbol(symbol, strike, option_type, order['exchange'], expiry_tag)
            if resolved_symbol:
                order['symbol'] = resolved_symbol
                logger.info(f"Resolved option symbol: {symbol} {strike} {option_type} -> {resolved_symbol} (Lot: {resolved_lotsize})")
                
                # set default quantity to lot size if not provided
                if not signal_data.get('quantity'):
                    order['quantity'] = str(resolved_lotsize) if resolved_lotsize else '1'
            else:
                 logger.warning(f"Could not resolve option symbol for {symbol} {strike} {option_type}. Using generic symbol.")
                 order['symbol'] = symbol
                 
            # If quantity is not set (generic symbol case), default to 1
            if 'quantity' not in order:
                 order['quantity'] = signal_data.get('quantity', '1')
        else:
            # Futures or cash
            order['symbol'] = symbol
            # Determine exchange based on symbol
            if symbol in ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']:
                order['exchange'] = 'NFO'
            elif symbol in ['SENSEX', 'BANKEX']:
                order['exchange'] = 'BFO'
            elif symbol in ['CRUDEOIL', 'GOLD', 'SILVER', 'NATURALGAS']:
                order['exchange'] = 'MCX'
            else:
                order['exchange'] = 'NSE'  # Default to NSE
        
        # Quantity - already set for options above, but ensure it exists for non-options
        if 'quantity' not in order:
            order['quantity'] = signal_data.get('quantity', '1')
        
        # Price and Order Type Logic
        price = signal_data.get('price')
        condition = signal_data.get('condition')
        
        if price:
            entry_price = float(price)
            order['price'] = str(price)
            
            # Smart Entry Logic: Fetch LTP to decide Order Type
            current_ltp = 0
            try:
                # Fetch quote with basic error handling
                # get_quotes is synchronous, so we just call it directly
                quote_res = get_quotes(exchange=order['exchange'], symbol=order['symbol'])

                if quote_res and 'lp' in quote_res:
                    current_ltp = float(quote_res['lp'])
                    logger.info(f"Smart Entry: Fetched LTP for {order['symbol']} = {current_ltp} (Entry: {entry_price})")
            except Exception as e:
                logger.error(f"Error fetching LTP for Smart Entry: {e}")

            # Define Logic Variants
            condition = signal_data.get('condition', '').lower()
            action = order['action'].upper()
            
            # Default to LIMIT if no LTP available
            final_pricetype = 'LIMIT'
            final_trigger = None
            
            if current_ltp > 0:
                # User Requirement:
                # Entry = 100, Current LTP = 100.1 to 101.5 → BUY (execute immediately)
                # Entry = 100, Current LTP > 101.5 → Skip/Wait (don't chase)
                # Entry = 100, Current LTP < 100 → SL Order (wait for breakout)
                
                min_entry_tolerance = 0.1  # Minimum 0.1 above entry
                max_entry_tolerance = 1.5  # Maximum 1.5 above entry
                
                if action == 'BUY':
                    if current_ltp < entry_price:
                        # Breakout Scenario (Wait for price to go UP to entry)
                        # SL Order: Trigger at entry+0.1, allow up to entry+1.5 on limit price
                        final_pricetype = 'SL'
                        final_trigger = str(entry_price + min_entry_tolerance)  # Trigger at entry+0.1
                        order['price'] = str(entry_price + max_entry_tolerance)  # Allow fill up to entry+1.5
                        logger.info(f"📊 Entry: Breakout (LTP {current_ltp} < Entry {entry_price}) → SL Order (Trigger: {entry_price + min_entry_tolerance}, Limit: {entry_price + max_entry_tolerance})")
                    
                    elif (entry_price + min_entry_tolerance) <= current_ltp <= (entry_price + max_entry_tolerance):
                        # Within Tolerance Window (Entry+0.1 to Entry+1.5) - USER REQUIREMENT
                        # LIMIT Order at LTP to ensure fill
                        final_pricetype = 'LIMIT'
                        order['price'] = str(current_ltp + 0.05)  # Slight buffer to ensure fill
                        logger.info(f"✅ Entry: Immediate (LTP {current_ltp} within {entry_price + min_entry_tolerance} to {entry_price + max_entry_tolerance}) → LIMIT @ {current_ltp + 0.05}")
                    
                    elif current_ltp < (entry_price + min_entry_tolerance):
                        # LTP is between entry and entry+0.1 - Wait for +0.1
                        error_msg = f"⏳ LTP {current_ltp} is below minimum entry {entry_price + min_entry_tolerance}. Waiting..."
                        logger.warning(error_msg)
                        raise ValueError(error_msg)
                        
                    else:
                        # LTP > Entry + 1.5: Don't chase, wait for pullback
                        error_msg = f"❌ LTP {current_ltp} is > {max_entry_tolerance} pts away from Entry {entry_price}. Waiting for pullback to {entry_price + min_entry_tolerance}-{entry_price + max_entry_tolerance} range."
                        logger.warning(error_msg)
                        raise ValueError(error_msg)
                
                elif action == 'SELL':
                    # Inverse logic for SELL
                    if current_ltp > entry_price:
                        # Breakdown Scenario (Wait for price to go DOWN to entry)
                        # SL Order: Trigger at entry, allow down to entry-1.5 on limit price
                        final_pricetype = 'SL'
                        final_trigger = str(entry_price)
                        order['price'] = str(entry_price - entry_tolerance)  # Allow fill down to entry-1.5
                        logger.info(f"📊 Entry: Breakdown (LTP {current_ltp} > Entry {entry_price}) → SL Order (Trigger: {entry_price}, Limit: {entry_price - entry_tolerance})")
                    
                    elif current_ltp >= (entry_price - entry_tolerance):
                        # Within Tolerance Window (Entry-1.5 to Entry)
                        final_pricetype = 'LIMIT'
                        order['price'] = str(entry_price - entry_tolerance)
                        logger.info(f"✅ Entry: Immediate (LTP {current_ltp} within {entry_price - entry_tolerance} to {entry_price}) → LIMIT @ {entry_price - entry_tolerance}")
                        
                    else:
                        # LTP < Entry - 1.5: Don't chase down, wait for pullback
                        error_msg = f"❌ LTP {current_ltp} is > {entry_tolerance} pts away from Entry {entry_price}. Waiting for pullback to {entry_price - entry_tolerance}-{entry_price} range."
                        logger.warning(error_msg)
                        raise ValueError(error_msg)

            else:
                # Fallback: No LTP - Use condition-based logic with STRICT entry+0.1 minimum
                min_entry_buffer = 0.1
                max_entry_buffer = 1.0
                
                if condition == 'above':
                    # BUY signal: Place SL order with trigger at entry+0.1 (NOT entry+0.0)
                    final_pricetype = 'SL'
                    final_trigger = str(entry_price + min_entry_buffer)  # Trigger at entry+0.1
                    order['price'] = str(entry_price + max_entry_buffer)  # Limit at entry+1.0
                    logger.info(f"Fallback Entry (above): No LTP → SL Order (Trigger: {entry_price + min_entry_buffer}, Limit: {entry_price + max_entry_buffer})")
                elif condition == 'below':
                    # SELL signal: Place SL order with trigger at entry-0.1
                    final_pricetype = 'SL'
                    final_trigger = str(entry_price - min_entry_buffer)
                    order['price'] = str(entry_price - max_entry_buffer)
                    logger.info(f"Fallback Entry (below): No LTP → SL Order (Trigger: {entry_price - min_entry_buffer}, Limit: {entry_price - max_entry_buffer})")
                else:
                    # 'at' condition: Simple LIMIT order at entry+0.1
                    final_pricetype = 'LIMIT'
                    order['price'] = str(entry_price + min_entry_buffer)
                    logger.info(f"Fallback Entry (at): No LTP → LIMIT @ {entry_price + min_entry_buffer}")
            
            # Apply determined types
            order['pricetype'] = final_pricetype
            if final_trigger:
                order['trigger_price'] = final_trigger
                
        else:
            order['price'] = '0'
            order['pricetype'] = 'MARKET'
            logger.info(f"No entry price provided -> Placing MARKET Order")
        
        # Product type
        order['product'] = 'MIS'  # Intraday by default (safer)

        # Inject original signal data for Sandbox/Trailing logic
        # This is passed via 'original_data' in place_order_service
        order['targets'] = signal_data.get('targets', [])
        order['signal_data'] = signal_data
        
        # Position size (lot size) - Removed as it causes Schema Validation Error
        # order['position_size'] = signal_data.get('quantity', '1')
        
        return order
    
    def get_stats(self) -> Dict:
        """Get execution statistics"""
        return {
            **self.stats,
            'enabled': self.enabled,
            'confidence_threshold': self.confidence_threshold
        }
        
    def _resolve_option_symbol(self, base_symbol: str, strike: str, option_type: str, exchange: str, expiry_tag: str = None) -> tuple[Optional[str], Optional[str]]:
        """
        Resolve generic option details to exact trading symbol from database
        Example: CRUDEOIL, 5000, CE, MCX -> CRUDEOIL26JAN265000CE
        """
        try:
            # Convert strike to float for comparison if needed, or string matching
            # Database stores strike as Float usually
            try:
                strike_val = float(strike)
            except ValueError:
                logger.error(f"Invalid strike price: {strike}")
                return None
                
            # Current date for filtering expired contracts
            now = datetime.now()
            
            # Query the database
            # We want symbols that match:
            # 1. Exchange
            # 2. Name (Underlying) or Symbol like Base%
            # 3. Strike equality
            # 4. Instrument type (CE/PE check via symbol suffix usually reliable)
            
            # Note: MCX symbols usually look like CRUDEOIL16JAN264800CE
            # NFO symbols: NIFTY26JAN22000CE
            
            query = db_session.query(SymToken).filter(
                SymToken.exchange == exchange,
                SymToken.strike == strike_val,
                SymToken.symbol.ilike(f'%{option_type}') # Ends with CE/PE
            )
            
            # Filter by underlying name/base symbol
            # Handles cases where Name is distinct from Symbol prefix
            if exchange == 'MCX':
                # MCX: Name is usually CRUDEOIL, Symbol starts with CRUDEOIL
                query = query.filter(SymToken.symbol.ilike(f'{base_symbol}%'))
            else:
                # NFO: Name is NIFTY, Symbol starts with NIFTY
                # For checks like DALBHARAT, Name might be distinct (ODISHA CEMENT), so use Symbol prefix
                query = query.filter(SymToken.symbol.ilike(f'{base_symbol}%'))
            
            # Fetch results
            matches = query.all()
            
            if not matches:
                return None, None
                
            # Sort by expiry to find nearest
            # Expiry format in DB is varied (String), need careful parsing or rely on DB order if consistent
            # Usually format is DD-MMM-YYYY or DD-MMM-YY
            
            # Helper to parse expiry
            def parse_expiry(token):
                if not token.expiry:
                    return datetime.max
                try:
                    return datetime.strptime(token.expiry, "%d-%b-%Y")
                except ValueError:
                    try:
                        return datetime.strptime(token.expiry, "%d-%b-%y")
                    except ValueError:
                         return datetime.max

            matches.sort(key=parse_expiry)
            
            # Filter out expired contracts
            # Fix: Compare dates only to include today's expiry (expiry is at end of day)
            active_matches = [m for m in matches if parse_expiry(m).date() >= now.date()]
            
            # Helper to check if expiry tag matches token expiry
            def matches_expiry_tag(token, tag):
                if not tag or not token.expiry:
                    return True
                
                tag = tag.upper()
                token_expiry = token.expiry.upper() # e.g. "26-DEC-24" or "26-DEC-2024"
                
                # Case 1: Month Only (e.g. "FEB")
                # Check if token expiry contains "-FEB-"
                if len(tag) == 3 and tag.isalpha():
                    return f"-{tag}-" in token_expiry
                
                # Case 2: Date + Month (e.g. "25JAN")
                # Normalize token to DDMMM format (or check components)
                # Token: "26-DEC-24" -> "26DEC" check
                token_parts = token_expiry.split('-')
                if len(token_parts) >= 2:
                    token_ddmmm = f"{token_parts[0]}{token_parts[1]}"
                    return tag == token_ddmmm
                
                return False

            # If expiry tag provided, filter further
            if expiry_tag:
                expiry_filtered = [m for m in active_matches if matches_expiry_tag(m, expiry_tag)]
                if expiry_filtered:
                    active_matches = expiry_filtered
                    logger.info(f"Filtered symbols by expiry '{expiry_tag}': {len(active_matches)} found")
                else:
                    logger.warning(f"No match found for expiry '{expiry_tag}', falling back to nearest")
            
            if active_matches:
                # Return the symbol and lotsize of the nearest expiry
                match = active_matches[0]
                return match.symbol, getattr(match, 'lotsize', '1')
                
            return None, None
            
        except Exception as e:
            logger.error(f"Error resolving symbol: {e}")
            return None, None


# Global instance
signal_executor = SignalExecutionService()
