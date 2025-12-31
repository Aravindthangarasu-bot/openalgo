from services.signal_classifier import SignalClassifier

classifier = SignalClassifier()

signal = """MUTHOOTFIN 3850 PE

ABOVE:- 100

SL:- 90

TARGET:- 105/110/120+"""

print(f"Testing: {signal}")
print('='*80)

is_signal, confidence, data = classifier.classify(signal)

print(f"Is Signal: {is_signal}")
print(f"Confidence: {confidence}")
print(f"\nParsed Data:")
for key, value in data.items():
    print(f"  {key}: {value}")

print(f"\nTarget Analysis:")
print(f"  Targets List: {data.get('targets')}")
print(f"  Number of Targets: {len(data.get('targets', []))}")
