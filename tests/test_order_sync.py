import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from services.price_monitor_service import PriceMonitorService
from services.position_monitor_service import position_monitor

class TestOrderSync(unittest.TestCase):
    def setUp(self):
        # Reset Singleton/Global states if necessary
        self.price_monitor = PriceMonitorService()
        self.position_monitor = position_monitor
        # Clear positions
        self.position_monitor.active_positions = {}

    @patch('database.auth_db.get_auth_token_dbquery')
    @patch('database.auth_db.decrypt_token')
    @patch('services.orderstatus_service.get_order_status')
    @patch('services.place_order_service.place_order')
    @patch('services.modify_order_service.modify_order')
    @patch('services.cancel_order_service.cancel_order')
    def test_end_to_end_flow(self, mock_cancel, mock_modify, mock_place, mock_status, mock_decrypt, mock_db_query):
        """
        Simulate a full lifecycle:
        1. Entry Signal -> Pending Open
        2. Entry Fill -> Active + Hard SL Placement
        3. Target Hit -> Trailing SL Update (Modify Hard SL)
        4. SL Hit -> Verify Hard SL 'Complete' detection or Manual Exit
        """
        async def run_test():
            # Setup Mocks
            mock_db_query.return_value = MagicMock(auth="encrypted_token", broker="zerodha", is_revoked=False)
            mock_decrypt.return_value = "valid_token"
            
            # --- PHASE 1: INITIALIZATION ---
            order_id = "ENTRY_ORDER_123"
            symbol = "NIFTY23DEC21000CE"
            entry_price = 100.0
            sl_price = 90.0
            target = 120.0
            
            # Manually add position as 'Signal Execution' would
            self.position_monitor.add_position(
                order_id=order_id,
                symbol=symbol,
                exchange="NFO",
                action="BUY",
                quantity=50,
                entry_price=entry_price,
                stop_loss=sl_price,
                targets=[target],
                signal_data={'product': 'MIS'},
                username='aravind'
            )
            
            # Verify Initial State
            pos = self.position_monitor.active_positions[order_id]
            self.assertEqual(pos['status'], 'pending_open')
            print("\n[TEST] Phase 1 Passed: Position initialized as 'pending_open'")

            # --- PHASE 2: ENTRY FILL & HARD SL PLACEMENT ---
            # Mock status as 'complete' for the Entry Order
            # First call is for Entry Order Check
            mock_status.side_effect = [
                (True, {'status': 'complete', 'filled_quantity': 50}, 200), # Entry Status
            ]
            
            # Mock Place Order for Hard SL
            sl_order_id = "SL_ORDER_999"
            mock_place.return_value = (True, {'orderid': sl_order_id, 'status': 'success'}, 200)

            # Trigger Price Monitor Check
            with patch.object(self.price_monitor, '_get_current_price', return_value=100.0):
                 await self.price_monitor._check_position(order_id, pos)
            
            # Verify Status is Active
            self.assertEqual(pos['status'], 'active')
            # Verify Hard SL was placed
            mock_place.assert_called() 
            args, _ = mock_place.call_args
            sl_order_payload = args[0]
            self.assertEqual(sl_order_payload['order_type'], 'SL')
            self.assertEqual(sl_order_payload['price'], str(sl_price))
            self.assertEqual(sl_order_payload['trigger_price'], str(sl_price))
            
            # Verify SL Order ID stored
            self.assertEqual(pos['sl_order_id'], sl_order_id)
            print(f"[TEST] Phase 2 Passed: Entry Filled -> Hard SL placed ({sl_order_id})")

            # --- PHASE 3: TRAILING (MODIFY HARD SL) ---
            # Reset mocks
            mock_place.reset_mock()
            mock_modify.return_value = (True, {'status': 'success'}, 200)
            
            # Mock get_order_status for Hard SL check (runs in _check_position now)
            # Hard SL is OPEN (not hit yet)
            mock_status.side_effect = [
                 (True, {'status': 'open'}, 200) 
            ]

            # Simulate Price Move to Target (120)
            # This should trigger trailing SL to Entry (100)
            # Update targets for test to allow stepping
            pos['signal_data']['targets'] = [110, 130] 
            
            current_price = 115.0 # Passed T1 (110)
            
            # Patch _get_current_price to return 115.0
            with patch.object(self.price_monitor, '_get_current_price', return_value=current_price):
                 await self.price_monitor._check_position(order_id, pos)

            # Verify Modify Order called on HARD SL ID
            mock_modify.assert_called()
            _, kwargs = mock_modify.call_args
            modify_payload = kwargs.get('order_data')
            self.assertEqual(modify_payload['orderid'], sl_order_id) # CRITICAL: Must modify SL Order, not Entry
            self.assertEqual(modify_payload['price'], str(entry_price)) # T1 hit -> Move to Entry
            print(f"[TEST] Phase 3 Passed: T1 Hit ({current_price}) -> Updated Hard SL ({sl_order_id}) to Entry ({entry_price})")

            # --- PHASE 4: EXACT PRICE EXIT (BROKER SIDE TRIGGER) ---
            # Scenario: Price drops. The Broker SL order triggers.
            # We simulate that the BROKER reports the Hard SL as 'COMPLETE'.
            mock_status.side_effect = [
                (True, {'status': 'complete'}, 200) # Hard SL Status
            ]
            
            # Current price finding (irrelevant if SL checks first, but required for flow)
            with patch.object(self.price_monitor, '_get_current_price', return_value=95.0):
                await self.price_monitor._check_position(order_id, pos)
            
            # Verify Position Removed
            self.assertNotIn(order_id, self.position_monitor.active_positions)
            print("[TEST] Phase 4 Passed: Hard SL Reported Complete -> Position Removed Locally")

        # Run async test
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_test())
        loop.close()

if __name__ == '__main__':
    unittest.main()
