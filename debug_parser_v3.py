from services.signal_classifier import SignalClassifier

classifier = SignalClassifier()

sig = "Natural gas 360 ce (22 jan exp) above 31 target 32, 32.1, 32.2 SL 30"

print(f"Testing: {sig}")
try:
    is_signal, confidence, data = classifier.classify(sig)
    print(f"Is Signal: {is_signal}")
    print(f"Data: {data}")
    
    # Check extraction explicitly
    print(f"Symbol: {data.get('symbol')}")
    print(f"Price: {data.get('price')}")
    print(f"Condition: {data.get('condition')}")
    print(f"Targets: {data.get('targets')}")
    print(f"SL: {data.get('sl')}")
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
