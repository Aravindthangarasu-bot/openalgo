from datetime import datetime

expiry_str = "16-JAN-26"

print(f"Testing parsing of {expiry_str}...")

try:
    # This is what dashboard.py does
    dt = datetime.strptime(expiry_str, '%d-%b-%Y')
    print(f"Success with %Y: {dt}")
except ValueError as e:
    print(f"Failed with %Y: {e}")

try:
    # This is what it SHOULD probably do (or support both)
    dt = datetime.strptime(expiry_str, '%d-%b-%y')
    print(f"Success with %y: {dt}")
except ValueError as e:
    print(f"Failed with %y: {e}")
