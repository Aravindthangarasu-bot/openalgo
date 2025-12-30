
import os
import sys
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path, override=True)
sys.path.append(os.path.dirname(__file__))
from database.symbol import db_session
from database.user_db import User

def list_users():
    users = db_session.query(User).all()
    print(f"Total Users: {len(users)}")
    for u in users:
        print(f"ID: {u.id}, Username: '{u.username}'")

if __name__ == "__main__":
    list_users()
