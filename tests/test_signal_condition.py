
import unittest
from services.signal_classifier import SignalClassifier

class TestSignalConditionParsing(unittest.TestCase):
    def setUp(self):
        self.classifier = SignalClassifier()

    def test_above_condition(self):
        text = "SENSEX 85200 PE ABOVE:- 320 SL:- 290 TARGET:- 340"
        _, _, signal = self.classifier.classify(text)
        self.assertEqual(signal['price'], '320')
        self.assertEqual(signal['condition'], 'above')

    def test_at_condition(self):
        text = "BUY RELIANCE @ 2400 SL 2380 TGT 2450"
        _, _, signal = self.classifier.classify(text)
        self.assertEqual(signal['price'], '2400')
        self.assertEqual(signal['condition'], '@')

    def test_no_condition(self):
        text = "BUY NIFTY 22000 CE 150" # Ambiguous if 150 is price, but assumed
        _, _, signal = self.classifier.classify(text)
        # Price regex might miss this if strictly looking for keyword, 
        # but the fallback logic catches it. 
        # Condition should be None/missing.
        self.assertIsNone(signal.get('condition'))

if __name__ == '__main__':
    unittest.main()
