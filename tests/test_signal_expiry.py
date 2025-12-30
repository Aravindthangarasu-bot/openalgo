
import unittest
from services.signal_classifier import SignalClassifier

class TestSignalExpiryParsing(unittest.TestCase):
    def setUp(self):
        self.classifier = SignalClassifier()

    def test_monthly_expiry_keyword(self):
        # "FEB"
        text = "BUY TCS FEB FUT @ 3400 SL 3350"
        is_signal, confidence, signal = self.classifier.classify(text)
        self.assertTrue(is_signal)
        self.assertEqual(signal['symbol'], 'TCS')
        self.assertEqual(signal['expiry'], 'FEB')

    def test_specific_date_expiry(self):
        # "25 JAN"
        text = "RELIANCE 25 JAN 2800 CE BUY @ 120"
        is_signal, confidence, signal = self.classifier.classify(text)
        self.assertTrue(is_signal)
        self.assertEqual(signal['symbol'], 'RELIANCE')
        self.assertEqual(signal['expiry'], '25JAN')  # Normalized spacing/case

    def test_date_with_ordinal_expiry(self):
        # "29th FEB"
        text = "BANKNIFTY 29th FEB 46000 PE BUY 400"
        is_signal, confidence, signal = self.classifier.classify(text)
        self.assertTrue(is_signal)
        self.assertEqual(signal['expiry'], '29FEB') # Normalized

    def test_expiry_at_end(self):
        # Expiry mentioned at the end
        text = "Sell INFY 1600 CE at 20 SL 10 Target 40 Jan Expiry"
        is_signal, confidence, signal = self.classifier.classify(text)
        self.assertTrue(is_signal)
        # Should detect JAN even if "Expiry" word is present
        self.assertIn('JAN', signal['expiry']) 

    def test_short_date_format(self):
         # "25JAN" (no space)
        text = "BUY NIFTY 25JAN 22000 CE @ 150"
        is_signal, confidence, signal = self.classifier.classify(text)
        self.assertTrue(is_signal)
        self.assertEqual(signal['expiry'], '25JAN')

if __name__ == '__main__':
    unittest.main()
