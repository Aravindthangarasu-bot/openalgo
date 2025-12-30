
import logging
from services.signal_classifier import SignalClassifier
import asyncio

# Setup logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("services.signal_classifier")
logger.setLevel(logging.INFO)

def test():
    classifier = SignalClassifier()
    
    # Test case from user
    text = """SENSEX 85400 PE

ABOVE:- 360

SL:- 330

TARGET:- 380/400/440+"""
    
    print(f"Testing Text:\n{text}\n")
    print("-" * 30)
    
    is_signal, confidence, extracted = classifier.classify(text)
    
    print(f"\nResult:\nIs Signal: {is_signal}\nConfidence: {confidence}\nExtracted: {extracted}")

if __name__ == "__main__":
    test()
