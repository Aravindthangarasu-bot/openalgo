import asyncio
import re
import logging
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from database.telegram_db import get_bot_config, update_bot_config
from utils.logging import get_logger
import os

logger = get_logger(__name__)

class TelegramSignalListener:
    def __init__(self):
        self.client = None
        self.is_running = False
        self.target_channel = None
        self.api_id = None
        self.api_hash = None
        self.session_string = None
        
        # Regex for generic signal parsing (Buy/Sell)
        # Matches: BUY/SELL [SYMBOL] [STRIKE] [TYPE] [PRICE] [SL] [TARGET]
        # Example: BUY NIFTY 22000 CE @ 150 SL 120 TGT 200
        self.signal_pattern = re.compile(
            r"(?P<action>BUY|SELL)\s+"
            r"(?P<symbol>[A-Z0-9]+)\s*"
            r"(?P<strike>\d+)?\s*"
            r"(?P<option_type>CE|PE)?\s*"
            r"(?:@|AT|ABOVE|CMP)?\s*(?P<price>[\d\.]+)\s*"
            r"SL\s*(?P<sl>[\d\.]+)\s*"
            r"TGT\s*(?P<tgt>[\d\.]+)",
            re.IGNORECASE
        )

    async def initialize(self):
        """Initialize the client from config"""
        try:
            # Load config from env or db
            self.api_id = os.getenv("TELEGRAM_API_ID")
            self.api_hash = os.getenv("TELEGRAM_API_HASH")
            self.target_channel = os.getenv("TELEGRAM_TARGET_CHANNEL")
            
            # Support multiple channels
            channels_env = os.getenv("TELEGRAM_CHANNELS", "")
            # Split and convert to int if possible (for IDs)
            self.channels = []
            if channels_env:
                for c in channels_env.split(","):
                    c = c.strip()
                    if c:
                        # Check if it's a numeric ID (potentially negative)
                        try:
                            self.channels.append(int(c))
                        except ValueError:
                            self.channels.append(c)
            
            # Fallback to single target channel if no list provided
            if not self.channels and self.target_channel:
                try:
                    self.channels = [int(self.target_channel)]
                except ValueError:
                    self.channels = [self.target_channel]
                
            self.session_string = os.getenv("TELEGRAM_SESSION_STRING")
            # Map to store resolved names: {id_or_username: display_title}
            self.channel_map = {} 
            self.message_buffer = {} # Buffer for history replay 

            if not self.api_id or not self.api_hash:
                logger.error("TELEGRAM_API_ID or TELEGRAM_API_HASH missing in .env")
                return False

            if self.session_string:
                self.client = TelegramClient(StringSession(self.session_string), self.api_id, self.api_hash)
            else:
                # First time login - will need phone auth
                self.client = TelegramClient(StringSession(), self.api_id, self.api_hash)
            
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Telegram Listener: {e}")
            return False

    async def connect(self):
        """Connect to Telegram"""
        try:
            if not self.client:
                await self.initialize()
            
            await self.client.connect()
            
            if not await self.client.is_user_authorized():
                logger.info("Client not authorized. Waiting for login.")
                return False
            
            self.is_running = True
            
            # Save session string for persistence if it changed
            new_session = self.client.session.save()
            if new_session != self.session_string:
                logger.info(f"New Session String: {new_session}")
            
            logger.info(f"Connected as: {(await self.client.get_me()).username}")
            
            # Start listening and resolve names
            if self.channels:
                await self.resolve_channel_names()
                # Fetch history for today (Visual Only - No Execution)
                await self.fetch_history()
                self._register_handlers()
            
            return True
            
        except Exception as e:
            logger.error(f"Connection error: {e}")
            self.is_running = False
            return False

    async def fetch_history(self):
        """Fetch messages from midnight today"""
        from datetime import datetime, time, timezone, timedelta
        
        # Calculate midnight (start of day) in local time (assuming server time) or UTC?
        # Telegram uses UTC usually, but client might adjust. 
        # Safest is just "today start".
        # Let's use simple local midnight for now, or UTC if preferred.
        # User is in IST (+5:30).
        
        # Get UTC midnight (safest baseline)
        now = datetime.now(timezone.utc)
        midnight_utc = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        logger.info(f"Fetching history since {midnight_utc}...")
        
        for channel in self.channels:
            try:
                # Use reverse=True (oldest to newest) to populate dashboard correctly
                # limit=None means all messages since offset_date
                # offset_date expects a datetime
                logger.info(f"Fetching history for {channel}...")
                msgs = []
                async for msg in self.client.iter_messages(channel, offset_date=midnight_utc, reverse=True):
                   msgs.append(msg)
                
                logger.info(f"Found {len(msgs)} messages for {channel}")
                
                # Use resolved name
                channel_name = self.channel_map.get(channel, str(channel))
                
                for msg in msgs:
                    if msg.text:
                         # Pass replay=True to prevent execution
                         await self.process_message(msg.text, channel_name, timestamp=msg.date, replay=True)
                         
                # Small delay to avoid flood wait
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Failed to fetch history for {channel}: {e}", exc_info=True)

    async def resolve_channel_names(self):
        """Resolve entity IDs to human-readable titles"""
        logger.info(f"Resolving names for channels: {self.channels}")
        for channel in self.channels:
            try:
                entity = await self.client.get_entity(channel)
                title = getattr(entity, 'title', None) or getattr(entity, 'username', None) or str(channel)
                self.channel_map[channel] = title
                logger.info(f"Resolved channel {channel} to '{title}'")
            except Exception as e:
                logger.warning(f"Could not resolve channel {channel}: {e}")
                self.channel_map[channel] = str(channel)

    async def send_code_request(self, phone_number):
        """Request OTP for login"""
        if not self.client:
            await self.initialize()
        await self.client.connect()
        return await self.client.send_code_request(phone_number)

    async def sign_in(self, phone_number, code, password=None):
        """Complete login with OTP"""
        try:
            await self.client.sign_in(phone=phone_number, code=code, password=password)
            self.session_string = self.client.session.save()
            logger.info("Successfully signed in!")
            self.is_running = True
            return self.session_string
        except Exception as e:
            logger.error(f"Sign in failed: {e}")
            raise e

    def _register_handlers(self):
        """Register message event handlers"""
        # Listen to ALL messages (Incoming & Outgoing) to catch self-tests
        @self.client.on(events.NewMessage(incoming=True, outgoing=True))
        async def handler(event):
            try:
                chat_id = event.message.chat_id
                
                # Debug Log: Print EVERY message source to see what's happening
                # This is critical for diagnosing why "Test channel 1" is ignored
                logger.debug(f"Received msg from ID {chat_id}: {event.message.text[:50]}")

                # Strict Filtering: Only process if in our configured channels
                if chat_id not in self.channels:
                    # Try resolving potential mismatches (int vs long)
                    # Telethon normalizes, but sometimes it differs
                    return

                # Get resolved name
                channel_name = self.channel_map.get(chat_id)
                if not channel_name:
                    try:
                        chat = await event.get_chat()
                        channel_name = chat.title or chat.username or str(chat.id)
                    except:
                        channel_name = str(chat_id)
                
                logger.info(f"New Message from {channel_name}: {event.message.text}")
                # Pass message date
                await self.process_message(event.message.text, channel_name, timestamp=event.message.date)
            except Exception as e:
                logger.error(f"Error processing message: {e}")


    async def process_message(self, text, channel_name="Unknown", timestamp=None, replay=False):
        """Parse message using intelligent rule-based classifier + regex fallback"""
        signal_data = {}
        parsed_status = "raw"
        signal_confidence = 0.0
        
        # Try rule-based classifier first
        try:
            from services.signal_classifier import classifier
            
            is_signal, confidence, extracted = classifier.classify(text)
            signal_confidence = confidence
            
            if is_signal and extracted:
                # Use extracted data from classifier
                signal_data = extracted
                logger.info(f"CLASSIFIER SIGNAL (confidence: {confidence:.2f}) from {channel_name}: {signal_data}")
                parsed_status = "parsed"
            else:
                logger.debug(f"Classifier: Not a signal (confidence: {confidence:.2f})")
        except Exception as e:
            logger.warning(f"Classifier failed, falling back to regex: {e}")
        
        # Fallback to regex if classifier didn't find a signal
        if not signal_data:
            match = self.signal_pattern.search(text)
            if match:
                signal_data = match.groupdict()
                logger.info(f"REGEX SIGNAL PARSED from {channel_name}: {signal_data}")
                parsed_status = "parsed"
                signal_confidence = 0.8  # Assume high confidence for regex matches
            else:
                logger.debug(f"Message from {channel_name} did not match any pattern")
        
        # Auto-execute signal if parsed successfully - SKIP IF REPLAY
        if parsed_status == "parsed" and signal_data and not replay:
            try:
                from services.signal_execution_service import signal_executor
                
                # Execute signal in background (don't block message processing)
                success, result_msg = await signal_executor.execute_signal(
                    signal_data=signal_data,
                    channel=channel_name,
                    raw_message=text,
                    confidence=signal_confidence
                )
                
                if success:
                    logger.info(f"✅ Auto-executed signal: {result_msg}")
                else:
                    logger.debug(f"Signal not executed: {result_msg}")
                    
            except Exception as e:
                logger.error(f"Signal execution error: {e}", exc_info=True)
            
        # Emit WebSocket event for dashboard
        try:
            from extensions import socketio
            # Format timestamp if present (ISO format for JS to parse easily)
            # Message date is usually a timezone-aware datetime object
            timestamp_str = timestamp.isoformat() if timestamp else None
            
            data = {
                'channel': channel_name,
                'message': text,
                'parsed': signal_data,
                'status': parsed_status,
                'timestamp': timestamp_str
            }
            
            # Add to buffer
            if channel_name not in self.message_buffer:
                self.message_buffer[channel_name] = []
            
            # Keep last 50 messages
            self.message_buffer[channel_name].insert(0, data)
            if len(self.message_buffer[channel_name]) > 50:
                self.message_buffer[channel_name].pop()
            
            socketio.emit('new_signal', data)
        except Exception as e:
            logger.error(f"Failed to emit signal event: {e}")

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
            self.is_running = False
            
    def get_history(self):
        """Return buffered history"""
        # Return flattened list sorted by arrival? 
        # Or dict? Let's return dict keyed by channel name so frontend can easy map.
        return self.message_buffer

# Global instance
telegram_listener = TelegramSignalListener()
