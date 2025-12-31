from services.signal_classifier import SignalClassifier

classifier = SignalClassifier()

# Test both signal formats shown in the image
signals = [
    "w@HEROMOTOCM 3650 PE (ABOVE:- 348 SL:- 94 TARGET:- 165/110/125***",
    "w@HEROMOTOCM 3650 PE @ 188 SL NG TGT 165 0"
]

for sig in signals:
    print(f"\n{'='*80}")
    print(f"Testing: {sig}")
    print('='*80)
    try:
        is_signal, confidence, data = classifier.classify(sig)
        print(f"Is Signal: {is_signal}")
        print(f"Confidence: {confidence}")
        print(f"Parsed Data: {data}")
        
        if data:
            print(f"\nKey Fields:")
            print(f"  Symbol: {data.get('symbol')}")
            print(f"  Strike: {data.get('strike')}")
            print(f"  Option Type: {data.get('option_type')}")
            print(f"  Price: {data.get('price')}")
            print(f"  Condition: {data.get('condition')}")
            print(f"  SL: {data.get('sl')}")
            print(f"  Targets: {data.get('targets')}")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
