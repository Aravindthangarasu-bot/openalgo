import asyncio
import os
import logging
from services.signal_execution_service import signal_executor

# Setup logging
logging.basicConfig(level=logging.INFO)

async def test_signal():
    print("🚀 Starting Signal Execution Test")
    
    # Mock Signal Data
    signal_data = {
        'symbol': 'NATURALGAS',
        'strike': '360',
        'option_type': 'CE',
        'expiry': '22JAN',
        'price': '31',
        'condition': 'above',
        'sl': '30',
        'stop_loss': '30',
        'targets': ['32', '32.1', '32.2'],
        'tgt': '32.2',
        'action': 'BUY'
    }
    
    channel = 'DebugRunner'
    raw_msg = "Natural gas 360 ce (22 jan exp) above 31 target 32, 32.1, 32.2 SL 30"
    
    print(f"Testing Signal: {signal_data}")
    
    try:
        success, msg = await signal_executor.execute_signal(
            signal_data=signal_data,
            channel=channel,
            raw_message=raw_msg,
            confidence=1.0
        )
        print(f"Execution Result: {success}, {msg}")
    except Exception as e:
        print(f"CRITICAL FAILURE: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(test_signal())
