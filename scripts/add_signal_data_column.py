
import sqlite3
import os

DB_PATH = 'db/sandbox.db'

def add_column():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    tables = ['sandbox_orders', 'sandbox_positions']
    
    for table in tables:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN signal_data TEXT")
            print(f"Added signal_data column to {table}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"Column signal_data already exists in {table}")
            else:
                print(f"Error altering {table}: {e}")
                
    conn.commit()
    conn.close()

if __name__ == "__main__":
    add_column()
