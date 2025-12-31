"""
Position Monitor Service - Tracks Active Auto-Executed Positions

Monitors positions created from auto-executed signals for:
- Entry price tracking
- Current stop-loss
- Multiple targets
- Position status

This service integrates with the trailing SL and auto-exit systems.
"""

import asyncio
from typing import Dict, List, Optional
from datetime import datetime
from utils.logging import get_logger

logger = get_logger(__name__)


class PositionMonitor:
    """Monitor and track active trading positions"""
    
    def __init__(self):
        self.active_positions = {}  # {order_id: position_data}
        self.position_history = []  # Completed positions
        
        logger.info("Position Monitor Service initialized")
        self.restore_from_sandbox()

    def restore_from_sandbox(self):
        """Restore active positions from Sandbox DB if in Analyze Mode"""
        try:
            from database.settings_db import get_analyze_mode
            if not get_analyze_mode():
                return

            from database.sandbox_db import SandboxPositions, SandboxOrders, db_session
            from database.auth_db import get_api_key_for_tradingview 
            import json

            # Fetch all OPEN sandbox positions (quantity != 0)
            positions = SandboxPositions.query.filter(SandboxPositions.quantity != 0).all()
            
            # Date Check: Close positions from previous days (Daily Reset)
            today_date = datetime.now().date()
            
            restored_count = 0
            for pos in positions:
                try:
                    # Check if position is from a previous day (Intraday/Daily Refresh logic)
                    # We treat all monitored positions as daily sessions for now per user request
                    if pos.created_at and pos.created_at.date() < today_date:
                        logger.info(f"🧹 Expiring stale position {pos.symbol} from {pos.created_at.date()} (Qty: {pos.quantity})")
                        pos.quantity = 0
                        pos.updated_at = datetime.now()
                        db_session.add(pos)
                        db_session.commit()
                        continue

                    # Parse signal data
                    signal_data = {}
                    if pos.signal_data:
                        signal_data = json.loads(pos.signal_data)
                    
                    fake_order_id = f"SANDBOX_{pos.id}"
                    
                    # 1. Try to get SL from Signal Data
                    sl = float(signal_data.get('sl', 0))
                    if sl == 0:
                         sl = float(signal_data.get('stop_loss', 0))
                    
                    # 2. Try to get SL from Active Pending Order (Hard SL)
                    # Look for Open SELL order (if Long) with trigger price
                    action = 'BUY' if pos.quantity > 0 else 'SELL'
                    exit_action = 'SELL' if action == 'BUY' else 'BUY'
                    
                    active_sl_order = SandboxOrders.query.filter_by(
                        user_id=pos.user_id,
                        symbol=pos.symbol,
                        exchange=pos.exchange,
                        product=pos.product,
                        action=exit_action,
                        order_status='open'
                    ).filter(SandboxOrders.price_type.in_(['SL', 'SL-M'])).order_by(SandboxOrders.order_timestamp.desc()).first()
                    
                    if not active_sl_order:
                        # Check what IS there
                        all_open = SandboxOrders.query.filter_by(
                             user_id=pos.user_id, symbol=pos.symbol, order_status='open'
                        ).all()
                        logger.info(f"   ⚠️ No Active SL Order found for {pos.symbol}. Open Orders: {[o.orderid + '(' + o.price_type + ')' for o in all_open]}")
                        
                        # Fallback: Look for ANY recent SL order (status doesn't matter, maybe it was cancelled/rejected but represents intent)
                        historical_sl = SandboxOrders.query.filter_by(
                            user_id=pos.user_id,
                            symbol=pos.symbol,
                            exchange=pos.exchange,
                            product=pos.product,
                            action=exit_action
                        ).filter(SandboxOrders.price_type.in_(['SL', 'SL-M'])).order_by(SandboxOrders.order_timestamp.desc()).first()
                        
                        if historical_sl and historical_sl.trigger_price:
                             sl = float(historical_sl.trigger_price)
                             # Don't set sl_order_id if it's not open, so we don't try to cancel it later
                             logger.info(f"   Using Historical SL Order {historical_sl.orderid} @ {sl} as intended Stop Loss")
                             
                    sl_order_id = None
                    if active_sl_order:
                        if active_sl_order.trigger_price:
                             sl = float(active_sl_order.trigger_price)
                             sl_order_id = active_sl_order.orderid
                             logger.info(f"   Found Active SL Order {sl_order_id} @ {sl} for restored position")

                    # 3. Fallback
                    if sl == 0 and pos.average_price:
                        # Fallback SL 10% below/above
                        sl = float(pos.average_price) * 0.9 if pos.quantity > 0 else float(pos.average_price) * 1.1

                    # Parse targets - check multiple field names
                    targets = signal_data.get('targets', [])
                    if not targets:
                        # Fallback to 'target' (single value)
                        single_target = signal_data.get('target') or signal_data.get('tgt')
                        if single_target:
                            targets = [float(single_target)]
                    
                    if isinstance(targets, str):
                        targets = [float(t) for t in targets.split(',') if t.strip()]
                    elif isinstance(targets, list):
                        # Ensure all are floats
                        targets = [float(t) for t in targets if t]
                    
                    # Construct Position Object
                    pos_data = {
                        'order_id': fake_order_id,
                        'symbol': pos.symbol,
                        'exchange': pos.exchange,
                        'action': action,
                        'quantity': abs(pos.quantity),
                        'entry_price': float(pos.average_price),
                        'current_sl': sl, # Current SL is the critical one
                        'original_sl': sl,
                        'final_target': float(targets[-1]) if targets else 0.0,
                        'targets': targets,
                        'signal_data': signal_data,
                        'username': pos.user_id,
                        'product': pos.product,
                        'sl_order_id': sl_order_id, # Link the SL order
                        'trailing_enabled': True,
                        'highest_price': float(pos.average_price), # Initialize highest price to entry
                        't1_exit_done': False # Initialize T1 State
                    }
                    
                    # Add to memory explicitly (bypass add_position to avoid re-logging or reprocessing)
                    self.active_positions[fake_order_id] = pos_data
                    
                    restored_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to restore position {pos.symbol}: {e}")
            
            if restored_count > 0:
                logger.info(f"♻️ Restored {restored_count} active positions from Sandbox DB.")
                
        except Exception as e:
            logger.error(f"Error restoring sandbox positions: {e}")
    
    def add_position(
        self,
        order_id: str,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        entry_price: float,
        stop_loss: float,
        targets: List[float],
        signal_data: Dict,
        username: str = 'aravind', # Added username for auth retrieval
        product: str = 'MIS' # Added product with default
    ):
        """
        Add a new position to monitoring
        
        Args:
            order_id: Broker order ID
            symbol: Trading symbol
            exchange: Exchange (NSE, NFO, MCX, etc.)
            action: BUY or SELL
            quantity: Number of shares/lots
            entry_price: Entry price
            stop_loss: Initial stop loss
            targets: List of target prices
            signal_data: Original signal data for reference
            username: User who owns this position
            product: Product type (MIS/NRML/CNC)
        """
        if not targets:
            targets = []
        
        # Calculate final target (maximum)
        final_target = max(targets) if targets else None
        
        position = {
            'order_id': order_id,
            'symbol': symbol,
            'exchange': exchange,
            'action': action,
            'quantity': quantity,
            'entry_price': entry_price,
            'original_sl': stop_loss,
            'current_sl': stop_loss,
            'targets': targets,
            'final_target': final_target,
            'highest_price': entry_price,  # Track highest price reached
            'final_target': final_target,
            'highest_price': entry_price,  # Track highest price reached
            'status': 'pending_open', # Start as pending, wait for fill
            'created_at': datetime.now(),
            'signal_data': signal_data,
            'username': username, # Store username
            'trailing_enabled': True,
            'sl_order_id': None,  # SL order ID from broker
            'product': product, # Store product type
        
            # Multi-target progressive trailing state
            'original_quantity': quantity,  # Initial position size
            'remaining_quantity': quantity,  # Current position size (decreases after partial exits)
            't1_hit': False,  # T1 target reached and 50% exited
            't2_hit': False,  # T2 target reached and SL trailed to T1
            't3_hit': False,  # T3 target reached and remaining exited
            't1_exit_done': False, # Track if partial exit at T1 is done (legacy field)
            't3_plus_10_start_time': None, # Track T3+10 timer start (legacy field)
        }
        
        self.active_positions[order_id] = position
        logger.info(f"Position added (Pending): {order_id} - {symbol} {action} @ {entry_price}")
    
    def update_sl(self, order_id: str, new_sl: float, sl_order_id: Optional[str] = None):
        """Update stop-loss for a position"""
        if order_id in self.active_positions:
            position = self.active_positions[order_id]
            old_sl = position['current_sl']
            position['current_sl'] = new_sl
            
            if sl_order_id:
                position['sl_order_id'] = sl_order_id
            
            # Persist to Sandbox DB if Analyze Mode
            try:
                from database.settings_db import get_analyze_mode
                if get_analyze_mode():
                     symbol = position.get('symbol')
                     username = position.get('username')
                     
                     from database.sandbox_db import SandboxPositions, db_session
                     import json
                     
                     db_pos = SandboxPositions.query.filter_by(user_id=username, symbol=symbol).filter(SandboxPositions.quantity != 0).first()
                     if db_pos:
                         sig_data = {}
                         if db_pos.signal_data:
                             try:
                                sig_data = json.loads(db_pos.signal_data)
                             except: pass
                         
                         sig_data['stop_loss'] = new_sl
                         db_pos.signal_data = json.dumps(sig_data)
                         
                         db_session.commit()
                         logger.info(f"💾 Persisted SL {new_sl} to Sandbox DB for {symbol}")
            except Exception as e:
                logger.error(f"Failed to persist SL update: {e}")
            
            logger.info(f"Position {order_id} SL updated: {old_sl} → {new_sl}")
            return True
        return False
    
    def update_target(self, order_id: str, new_target: float):
        """Update target for a position"""
        if order_id in self.active_positions:
            position = self.active_positions[order_id]
            old_target = position.get('final_target')
            position['final_target'] = new_target
            
            # Persist to Sandbox DB if Analyze Mode
            try:
                from database.settings_db import get_analyze_mode
                if get_analyze_mode():
                     symbol = position.get('symbol')
                     username = position.get('username')
                     
                     from database.sandbox_db import SandboxPositions, db_session
                     import json
                     
                     db_pos = SandboxPositions.query.filter_by(user_id=username, symbol=symbol).filter(SandboxPositions.quantity != 0).first()
                     if db_pos:
                         sig_data = {}
                         if db_pos.signal_data:
                             try:
                                sig_data = json.loads(db_pos.signal_data)
                             except: pass
                         
                         sig_data['target'] = new_target
                         db_pos.signal_data = json.dumps(sig_data)
                         
                         db_session.commit()
                         logger.info(f"💾 Persisted Target {new_target} to Sandbox DB for {symbol}")
            except Exception as e:
                logger.error(f"Failed to persist Target update: {e}")

            logger.info(f"Position {order_id} Target updated: {old_target} → {new_target}")
            return True
        return False
        
    def update_targets(self, order_id: str, targets: List[float]):
        """Update multiple targets for a position"""
        if order_id in self.active_positions:
            position = self.active_positions[order_id]
            old_targets = position.get('targets', [])
            position['targets'] = targets
            
            # Persist to Sandbox DB if Analyze Mode
            try:
                from database.settings_db import get_analyze_mode
                if get_analyze_mode():
                     symbol = position.get('symbol')
                     username = position.get('username')
                     
                     from database.sandbox_db import SandboxPositions, db_session
                     import json
                     
                     db_pos = SandboxPositions.query.filter_by(user_id=username, symbol=symbol).filter(SandboxPositions.quantity != 0).first()
                     if db_pos:
                         sig_data = {}
                         if db_pos.signal_data:
                             try:
                                sig_data = json.loads(db_pos.signal_data)
                             except: pass
                         
                         sig_data['targets'] = targets
                         db_pos.signal_data = json.dumps(sig_data)
                         
                         db_session.commit()
                         logger.info(f"💾 Persisted Targets {targets} to Sandbox DB for {symbol}")
            except Exception as e:
                logger.error(f"Failed to persist Targets update: {e}")

            logger.info(f"Position {order_id} Targets updated: {old_targets} → {targets}")
            return True
        return False

    def update_t3_timer(self, order_id: str, start_time: datetime):
        """Update T3+10 timer start time"""
        if order_id in self.active_positions:
            self.active_positions[order_id]['t3_plus_10_start_time'] = start_time
            logger.debug(f"Position {order_id} T3+10 Timer Started: {start_time}")
            return True
        return False
    
    def update_status(self, order_id: str, new_status: str):
        """Update position status"""
        if order_id in self.active_positions:
            self.active_positions[order_id]['status'] = new_status
            logger.info(f"Position {order_id} status updated to {new_status}")
            return True
        return False

    def update_sl_order_id(self, order_id: str, sl_order_id: str):
        """Update SL Order ID for the position"""
        if order_id in self.active_positions:
            self.active_positions[order_id]['sl_order_id'] = sl_order_id
            logger.info(f"Position {order_id} linked to SL Order {sl_order_id}")
            return True
        return False

    def update_highest_price(self, order_id: str, current_price: float):
        """Track the highest price reached for trailing calculation"""
        if order_id in self.active_positions:
            position = self.active_positions[order_id]
            if current_price > position['highest_price']:
                position['highest_price'] = current_price
                logger.debug(f"Position {order_id} new high: {current_price}")
                return True
        return False
    
    def update_quantity(self, order_id: str, new_quantity: int):
        """Update position quantity after partial exit"""
        if order_id in self.active_positions:
            self.active_positions[order_id]['quantity'] = new_quantity
            logger.info(f"Position {order_id} quantity updated to {new_quantity}")
            return True
        return False
    
    def mark_t1_exit_done(self, order_id: str):
        """Mark partial exit at T1 as completed"""
        if order_id in self.active_positions:
            self.active_positions[order_id]['t1_exit_done'] = True
            logger.info(f"Position {order_id} marked as T1 Exit Done")
            return True
        return False
    
    def update_remaining_quantity(self, order_id: str, new_quantity: int):
        """Update remaining quantity after partial exit"""
        if order_id in self.active_positions:
            old_qty = self.active_positions[order_id].get('remaining_quantity', 0)
            self.active_positions[order_id]['remaining_quantity'] = new_quantity
            logger.info(f"Position {order_id} remaining quantity: {old_qty} → {new_quantity}")
            
            # Persist to Sandbox DB if in analyze mode
            try:
                from database.settings_db import get_analyze_mode
                if get_analyze_mode():
                    symbol = self.active_positions[order_id].get('symbol')
                    username = self.active_positions[order_id].get('username')
                    
                    from database.sandbox_db import SandboxPositions, db_session
                    import json
                    
                    db_pos = SandboxPositions.query.filter_by(user_id=username, symbol=symbol).filter(SandboxPositions.quantity != 0).first()
                    if db_pos:
                        sig_data = {}
                        if db_pos.signal_data:
                            try:
                                sig_data = json.loads(db_pos.signal_data)
                            except: pass
                        
                        sig_data['remaining_quantity'] = new_quantity
                        db_pos.signal_data = json.dumps(sig_data)
                        db_session.commit()
                        logger.debug(f"Persisted remaining_quantity={new_quantity} to Sandbox DB")
            except Exception as e:
                logger.error(f"Failed to persist remaining_quantity: {e}")
            
            return True
        return False
    
    def set_target_hit_flag(self, order_id: str, flag_name: str, value: bool = True):
        """Set t1_hit, t2_hit, or t3_hit flag"""
        if order_id in self.active_positions:
            self.active_positions[order_id][flag_name] = value
            logger.info(f"Position {order_id} {flag_name} = {value}")
            
            # Persist to Sandbox DB if in analyze mode
            try:
                from database.settings_db import get_analyze_mode
                if get_analyze_mode():
                    symbol = self.active_positions[order_id].get('symbol')
                    username = self.active_positions[order_id].get('username')
                    
                    from database.sandbox_db import SandboxPositions, db_session
                    import json
                    
                    db_pos = SandboxPositions.query.filter_by(user_id=username, symbol=symbol).filter(SandboxPositions.quantity != 0).first()
                    if db_pos:
                        sig_data = {}
                        if db_pos.signal_data:
                            try:
                                sig_data = json.loads(db_pos.signal_data)
                            except: pass
                        
                        sig_data[flag_name] = value
                        db_pos.signal_data = json.dumps(sig_data)
                        db_session.commit()
                        logger.debug(f"Persisted {flag_name}={value} to Sandbox DB")
            except Exception as e:
                logger.error(f"Failed to persist {flag_name}: {e}")
            
            return True
        return False
    
    def get_position(self, order_id: str) -> Optional[Dict]:
        """Get position details"""
        return self.active_positions.get(order_id)
    
    def get_active_positions(self) -> Dict:
        """Get all active positions"""
        return self.active_positions.copy()
    
    def remove_position(self, order_id: str, reason: str = "closed"):
        """Remove position from active monitoring"""
        if order_id in self.active_positions:
            position = self.active_positions.pop(order_id)
            position['status'] = reason
            position['closed_at'] = datetime.now()
            
            # Add to history
            self.position_history.append(position)
            
            # Keep only last 100 in history
            if len(self.position_history) > 100:
                self.position_history.pop(0)
            
            logger.info(f"Position removed: {order_id} - Reason: {reason}")
            return position
        return None
    
    def disable_trailing(self, order_id: str):
        """Disable trailing SL for a position"""
        if order_id in self.active_positions:
            self.active_positions[order_id]['trailing_enabled'] = False
            logger.info(f"Trailing disabled for position {order_id}")
            return True
        return False
    
    def enable_trailing(self, order_id: str):
        """Enable trailing SL for a position"""
        if order_id in self.active_positions:
            self.active_positions[order_id]['trailing_enabled'] = True
            logger.info(f"Trailing enabled for position {order_id}")
            return True
        return False
    
    def get_stats(self) -> Dict:
        """Get monitoring statistics"""
        return {
            'active_positions': len(self.active_positions),
            'total_history': len(self.position_history),
            'positions': [
                {
                    'order_id': p['order_id'],
                    'symbol': p['symbol'],
                    'entry': p['entry_price'],
                    'current_sl': p['current_sl'],
                    'final_target': p['final_target'],
                    'trailing': p['trailing_enabled']
                }
                for p in self.active_positions.values()
            ]
        }


# Global instance
position_monitor = PositionMonitor()
