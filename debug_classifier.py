from services.signal_classifier import classifier

# "08ABB" is in the CSV (line 2 of all_symbols.csv)
# "MARUTI" is in the CSV
# "ACC" is in the CSV
test_messages = [
    "BUY 08ABB AT 1020 SL 1000 TGT 1050",
    "SHORT ACC ABOVE 2200 SL 2250 TGT 2100",
    "**DALBHARAT 2180 PE ABOVE:- 24 SL:- 18 TARGET:- 27/31/38+**",  # Existing test
    "BUY ZOMATO 200 CE @ 5 SL 2 TGT 10"  # Likely in CSV
]

print("Valid Symbols Loaded:", len(classifier.valid_symbols))

for msg in test_messages:
    is_signal, confidence, extracted = classifier.classify(msg)
    print(f"Message: {msg}")
    print(f"Is Signal: {is_signal} (Confidence: {confidence:.2f})")
    print(f"Extracted: {extracted}")
    print("-" * 50)
