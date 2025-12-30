import os
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv

# Load env vars
load_dotenv()

api_id = os.getenv("TELEGRAM_API_ID")
api_hash = os.getenv("TELEGRAM_API_HASH")
session_string = os.getenv("TELEGRAM_SESSION_STRING")

if not api_id or not api_hash:
    print("Error: TELEGRAM_API_ID or TELEGRAM_API_HASH not found in .env")
    exit(1)

print(f"Initializing Telegram Client...")
print(f"Please follow the prompts to log in.")

# Use a StringSession so we can print the string at the end
# If session_string exists, try to reuse it (though user likely wants to re-auth if they asked for this)
# But let's respect it if it works.
if session_string:
    print("Found existing session string, testing connection...")
    client = TelegramClient(StringSession(session_string), api_id, api_hash)
else:
    print("No session string found. Starting fresh login...")
    client = TelegramClient(StringSession(), api_id, api_hash)

async def main():
    # client.start() is interactive and will use input()
    # It handles phone -> code -> password flow automatically
    await client.start()
    
    print("\n--------------------------------------------------")
    print("AUTHENTICATION SUCCESSFUL!")
    print("--------------------------------------------------")
    print("Here is your SESSION STRING (save this to .env):")
    print("\n" + client.session.save() + "\n")
    print("--------------------------------------------------")

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
