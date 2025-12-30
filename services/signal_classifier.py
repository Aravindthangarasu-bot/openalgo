"""
Rule-Based Signal Classifier - Enhanced with Real-World Training Data

Based on research of actual Telegram trading groups, this classifier distinguishes
between trading signals and market commentary using pattern recognition.

SIGNAL Examples (SHOULD detect):
- "NIFTY 26000 CE LONG Entry: 150 SL: 120 TP: 200"
- "BUY BANKNIFTY 44500 PE @ 180 SL 220 TGT 100"
- "SENSEX 85200 PE ABOVE 350 SL 320 TARGET 370"
- "SELL CRUDEOIL 6500 @ 6520 SL 6550 TGT 6450"
- "Stock: RELIANCE Long Price: 2800 SL: 2750 TP: 2900"

COMMENTARY Examples (should NOT detect):
- "NIFTY AND SENSEX BOTH SIDEWAY WAIT FOR ZONE BREAKOUT"
- "Market looking bullish, watch 26000 level"
- "Good morning traders! Pre-market analysis attached"
- "What's your view on today's market?"
- "NIFTY testing resistance at 26200, expecting pullback"
- "Breaking news: RBI announces rate cut"
"""

import re
from typing import Dict, Tuple, Optional
from utils.logging import get_logger

import os
import csv
logger = get_logger(__name__)


class SignalClassifier:
    """Intelligent rule-based classifier for trading signals"""
    
    def __init__(self):
        # Load valid symbols from CSV
        self.valid_symbols = set()
        try:
            csv_path = os.path.join(os.path.dirname(__file__), 'symbols.csv')
            if os.path.exists(csv_path):
                with open(csv_path, 'r') as f:
                    reader = csv.reader(f)
                    next(reader, None)  # Skip header
                    for row in reader:
                        if row:
                            self.valid_symbols.add(row[0].strip().upper())
                logger.info(f"Loaded {len(self.valid_symbols)} symbols from CSV")
            else:
                logger.warning(f"Symbols file not found at {csv_path}")
        except Exception as e:
            logger.error(f"Failed to load symbols: {e}")

        # Action keywords (highest weight) - MUST HAVE for signals
        self.action_keywords = {
            'buy': 12, 'sell': 12, 'long': 10, 'short': 10,
            'exit': 8, 'square': 7, 'book': 6, 'close': 5
        }
        
        # Trading instrument keywords
        self.instrument_keywords = {
            'nifty': 8, 'banknifty': 8, 'finnifty': 8, 'midcpnifty': 8,
            'sensex': 8, 'bankex': 8, 
            'crude': 7, 'crudeoil': 7, 'gold': 7, 'silver': 7,
            'naturalgas': 7, 'copper': 6, 'zinc': 6,
            'ce': 7, 'pe': 7, 'fut': 7, 'call': 6, 'put': 6
        }
        
        # Trading parameter keywords - These indicate a REAL signal
        self.param_keywords = {
            'sl': 8, 'stoploss': 8, 'stop': 6,  # Increased weight - critical
            'tgt': 8, 'target': 8, 'tp': 8,      # Increased weight - critical
            'entry': 6, 'cmp': 5, 'ltp': 5,
            'lot': 3, 'qty': 3, 'quantity': 3,
            'above': 5, 'below': 5, 'near': 4, 'around': 4,
            'price': 3, 'level': 0  # 'level' is neutral, used in commentary too
        }
        
        # Noise keywords - Strong indicators of commentary/analysis
        self.noise_keywords = {
            # Greetings and pleasantries
            'good': -4, 'morning': -4, 'evening': -3, 'hello': -4,
            'thanks': -3, 'thank': -3, 'welcome': -3, 'please': -2,
            
            # Market commentary and analysis
            'looking': -4, 'trend': -3, 'trending': -3,
            'analysis': -5, 'view': -4, 'opinion': -4,
            'think': -4, 'expect': -3, 'expecting': -3,
            'might': -3, 'may': -3, 'could': -3, 'should': -3,
            'would': -3, 'will': -2, 'going': -2,
            
            # Waiting/watching indicators
            'wait': -6, 'waiting': -6, 'watch': -5, 'watching': -5,
            'observe': -4, 'monitor': -3,
            
            # Technical commentary
            'sideway': -6, 'sideways': -6, 'range': -4, 'ranging': -4,
            'breakout': -5, 'breakdown': -5, 'zone': -4, 'level': -3,
            'resistance': -4, 'support': -4, 'testing': -4,
            'bullish': -4, 'bearish': -4, 'neutral': -4,
            
            # Questions and uncertain language
            'what': -4, 'how': -4, 'when': -4, 'where': -3,
            'question': -5, '?': -3,
            
            # Multiple/general references
            'both': -4, 'all': -3, 'everyone': -4, 'traders': -2,
            
            # News/updates
            'news': -4, 'update': -4, 'breaking': -4, 'announcement': -4,
            'report': -3, 'data': -2,
            
            # Educational content
            'learn': -4, 'guide': -4, 'tutorial': -4, 'tips': -3,
            'strategy': -3, 'method': -3,
            
            # Pre-market/post-market analysis
            'premarket': -4, 'pre-market': -4, 'postmarket': -4,
            'market': -1  # Weak negative - appears in both
        }
        
        # Regex patterns for numbers (prices, strikes, etc.)
        self.price_pattern = re.compile(r'\b\d{2,6}(?:\.\d{1,2})?\b')
        self.strike_pattern = re.compile(r'\b\d{3,6}\b')  # 3-6 digit strikes (supports stocks/MCX)
        
        # Signal structure patterns - Strong indicators
        self.signal_patterns = [
            # BUY/SELL SYMBOL STRIKE CE/PE @ PRICE SL X TGT Y
            re.compile(r'(buy|sell|long|short)\s+\w+\s+\d+\s+(ce|pe)', re.I),
            
            # Has both SL and TARGET (critical for real signals)
            re.compile(r'(?:sl|stoploss|stop).*(?:tgt|target|tp)', re.I),
            re.compile(r'(?:tgt|target|tp).*(?:sl|stoploss|stop)', re.I),
            
            # Entry + SL/TGT format
            re.compile(r'(?:entry|above|below|cmp|ltp)[:-]*\s+\d+.*(?:sl|target)', re.I),
            
            # SYMBOL STRIKE TYPE ABOVE/BELOW SL TARGET
            re.compile(r'\w+\s+\d{3,6}\s+(ce|pe)\s+(?:above|below|near|@|cmp).*sl.*target', re.I),
            re.compile(r'\w+\s+\d{3,6}\s+(ce|pe).*above', re.I),
            
            # Stock format: "Stock: XYZ Long/Short Price: X SL: Y TP: Z"
            re.compile(r'stock:.*(?:long|short).*price:.*(?:sl|tp)', re.I),
        ]
        
        # Anti-patterns - Strong signals this is NOT a trading call
        self.anti_patterns = [
            # Questions
            re.compile(r'\?', re.I),
            
            # Wait/watch for something
            re.compile(r'wait\s+for', re.I),
            re.compile(r'watch\s+(?:for|out)', re.I),
            
            # Multiple instruments without specific action
            re.compile(r'(?:both|all).*(?:nifty|sensex|banknifty)', re.I),
            
            # News/updates
            re.compile(r'(?:breaking|latest)\s+(?:news|update)', re.I),
            
            # Educational
            re.compile(r'(?:learn|guide|tutorial|tips|strategy)', re.I),
        ]
    
    def classify(self, text: str) -> Tuple[bool, float, Optional[Dict]]:
        """
        Classify if text is a trading signal
        
        Returns:
            Tuple of (is_signal: bool, confidence: float 0-1, extracted_data: dict)
        """
        text_lower = text.lower()
        score = 0
        
        # Check anti-patterns first (quick rejection)
        for anti_pattern in self.anti_patterns:
            if anti_pattern.search(text):
                score -= 10
                logger.debug(f"Anti-pattern detected: {anti_pattern.pattern}")
        
        # 1. Check action keywords
        action_found = None
        for keyword, weight in self.action_keywords.items():
            if re.search(r'\b' + keyword + r'\b', text_lower):
                score += weight
                if not action_found and keyword in ['buy', 'sell', 'long', 'short']:
                    action_found = keyword.upper()
                    if keyword in ['long', 'short']:
                        action_found = 'BUY' if keyword == 'long' else 'SELL'
        
        # 2. Check instrument keywords
        for keyword, weight in self.instrument_keywords.items():
            if re.search(r'\b' + keyword + r'\b', text_lower):
                score += weight
        
        # 3. Check parameter keywords (SL/TGT are CRITICAL)
        has_sl = False
        has_tgt = False
        for keyword, weight in self.param_keywords.items():
            if re.search(r'\b' + keyword + r'\b', text_lower):
                score += weight
                if keyword in ['sl', 'stoploss', 'stop']:
                    has_sl = True
                if keyword in ['tgt', 'target', 'tp']:
                    has_tgt = True
        
        # Bonus for having BOTH SL and TGT (hallmark of real signal)
        if has_sl and has_tgt:
            score += 12
            logger.debug("Has both SL and TGT - strong signal indicator")
        
        # 4. Check noise keywords (subtract score)
        for keyword, weight in self.noise_keywords.items():
            if keyword == '?':
                if keyword in text:
                    score += weight
            else:
                if re.search(r'\b' + keyword + r'\b', text_lower):
                    score += weight  # weight is negative
        
        # 5. Pattern bonuses
        prices = self.price_pattern.findall(text)
        if len(prices) >= 3:  # Entry + SL + TGT
            score += 8
        elif len(prices) >= 2:
            score += 4
        
        # Check for signal structure patterns
        pattern_matched = False
        for pattern in self.signal_patterns:
            if pattern.search(text):
                score += 10
                pattern_matched = True
                logger.debug(f"Pattern matched: {pattern.pattern}")
                break
        
        # 6. Calculate confidence
        # Normalize score to 0-1 range
        # Updated threshold: Real signals should score 25+
        confidence = min(1.0, max(0.0, score / 35))
        
        # Decision threshold - more strict now
        is_signal = score >= 20 and confidence >= 0.5
        
        # 7. Extract basic data if it's a signal
        extracted = None
        if is_signal:
            extracted = self._extract_signal_data(text, action_found)
            
            # Quality check: Require at least action OR (symbol + entry condition)
            has_meaningful_data = (
                extracted.get('action') or 
                (extracted.get('symbol') and (extracted.get('price') or extracted.get('sl') or extracted.get('tgt')))
            )
            
            if not has_meaningful_data:
                logger.debug(f"Signal downgraded - insufficient data: {extracted}")
                is_signal = False
                confidence = confidence * 0.5
                extracted = None
        
        logger.debug(f"Classification score: {score}, confidence: {confidence:.2f}, is_signal: {is_signal}")
        return is_signal, confidence, extracted
    
    def _extract_signal_data(self, text: str, action: str) -> Dict:
        """Extract structured data from signal using advanced regex patterns"""
        logger.info(f"DEBUG EXTRACT: Processing text: {text!r}")
        data = {}
        
        if action:
            data['action'] = action
        
        # 1. Extract Symbol
        # Uses loaded symbols list or defaults + Regex
        common_indices = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX', 'CRUDEOIL', 'GOLD', 'SILVER', 'NATURALGAS']
        
        # Regex for common indices + loaded symbols (if not too huge, otherwise use lookup)
        # Note: Constructing regex from 5000 symbols is heavy. Better to Extract Words -> Check Set.
        
        # First check generic pattern: SYMBOL (Word) present in text
        # This allows capturing "BUY ACC" or "SELL TATASTEEL"
        if self.valid_symbols:
            # Tokenize text (uppercase)
            words = re.findall(r'\b[A-Z]{3,15}\b', text.upper())
            for w in words:
                if w in self.valid_symbols or w in common_indices:
                    # Preference: If we find a symbol that is near "BUY" or "SELL" or matches Generic Pattern
                    data['symbol'] = w
                    break
        
        # Fallback to regex for complex cases (like "NIFTY DEC FUT") if not simple match
        # Handles: "RELIANCE", "HDFC BANK (HDFCBANK)", "BANKNIFTY", "NIFTY DEC FUT", "NATURAL GAS"
        symbol_pattern = r'\b(nifty|banknifty|finnifty|midcpnifty|sensex|bankex|crude\s*oil|crude|gold|silver|natural\s*gas|tcs|infy|reliance|hdfc\s*bank|icici\s*bank|sbine?)\b'
        symbol_match = re.search(symbol_pattern, text, re.I)
        
        # Check for symbol inside parentheses if not found initially (e.g., "HDFC BANK (HDFCBANK)")
        if not symbol_match:
             paren_symbol = re.search(r'\(([A-Z]+)\)', text)
             if paren_symbol:
                 data['symbol'] = paren_symbol.group(1).upper()
        elif symbol_match:
            raw_symbol = symbol_match.group(1).upper()
            # Normalize multi-word symbols
            if 'NATURAL' in raw_symbol:
                data['symbol'] = 'NATURALGAS'
            elif 'CRUDE' in raw_symbol:
                data['symbol'] = 'CRUDEOIL'
            else:
                data['symbol'] = raw_symbol.replace(' ', '')
        
        # Fallback: Generic Symbol Extraction (WORD STRIKE TYPE)
        # Matches: "DALBHARAT 2180 PE", "MARUTI 16700 CE"
        if 'symbol' not in data:
            # Look for Word followed by Number followed by CE/PE
            generic_match = re.search(r'\b([A-Z]{3,15})\s+(\d{3,6})\s+(?:CE|PE)', text, re.I)
            if generic_match:
                data['symbol'] = generic_match.group(1).upper()
                # We can also capture strike here if we want, but letting step 2 handle it is safer
                # data['strike'] = generic_match.group(2)

        # 2. Extract Option Details (Strike & Type)
        strike_match = re.search(r'\b(\d{3,6})\b', text)
        if strike_match:
            data['strike'] = strike_match.group(1)
        
        option_match = re.search(r'\b(CE|PE|Call|Put)\b', text, re.I)
        if option_match:
            otype = option_match.group(1).upper()
            data['option_type'] = 'CE' if otype in ['CE', 'CALL'] else 'PE'

        # 3. Extract Expiry Date
        # Matches: "25 JAN", "25th JAN", "25JAN", "FEB", "FEB EXPY"
        # Regex captures: (Day)(Ordinal?)(Month) OR (Month)
        # Note: We prioritize specific dates (25 JAN) over just Month (JAN) if both exist
        
        month_pattern = r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[a-z]*'
        
        # Pattern A: Specific Date (25 JAN, 25th JAN, 25JAN)
        # Group 1: Day, Group 3: Month
        specific_expiry = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s*' + month_pattern, text, re.I)
        
        # Pattern B: Month Only (FEB Future)
        # Group 1: Month
        month_expiry = re.search(r'\b' + month_pattern + r'\b', text, re.I)
        
        if specific_expiry:
            day = specific_expiry.group(1)
            month = specific_expiry.group(2)[:3].upper() # Take first 3 chars
            data['expiry'] = f"{day}{month}"
        elif month_expiry:
            data['expiry'] = month_expiry.group(1)[:3].upper()

        # 3. Extract Entry Price
        # Robust pattern: Keyword + optional junk + currency + number
        # Matches: "above 2500", "Entry: 350", "at ₹1400", "Buy @ 1650"
        # 3. Extract Entry Price and Condition
        # Robust pattern: Keyword (captured) + optional separator (:- or :) + optional junk + currency + number (captured)
        # Matches: "above 2500", "above:- 24", "Entry: 350", "at ₹1400", "Buy @ 1650"
        price_patterns = [
            r'(above|below|around|near|@|at|cmp|price|entry)(?:[:-]*)\s*[^0-9\n]*\s*(\d+(?:\.\d+)?)'
        ]
        
        for p in price_patterns:
            match = re.search(p, text, re.I)
            if match:
                condition_word = match.group(1).lower()
                data['price'] = match.group(2)
                
                # Normalize condition
                if condition_word in ['above', 'below', 'around', 'near', 'at', '@']:
                    data['condition'] = condition_word
                break
        
        # Fallback: If still no price, using the logic of finding the first number that isn't a strike
        if 'price' not in data:
             # Find all potential prices (floats or integers)
             all_nums = re.findall(r'\b\d+(?:\.\d+)?\b', text)
             for num in all_nums:
                 # Filter out likely Strike prices (often large round numbers like 45000, 21000) if we have a strike
                 # Or if it matches exactly the strike extracted earlier
                 if data.get('strike') and (num == data.get('strike') or float(num) == float(data.get('strike'))):
                     continue
                 # Filter out if it matches a known SL or Target (extracted later, so we might need a 2nd pass or be smart)
                 # Heuristic: Start with first valid number
                 data['price'] = num
                 break
        
        # 4. Extract Stop Loss (SL)
        # Matches: "SL 2485", "SL:- 18", "Stop Loss: 320"
        sl_match = re.search(r'(?:stop\s*loss|sl|stop)\s*(?:[:-]*)\s*[₹]?\s*(\d+(?:\.\d+)?)', text, re.I)
        if sl_match:
            data['sl'] = sl_match.group(1)
            data['stop_loss'] = sl_match.group(1)

        # 5. Extract Targets
        # Matches: "Target: 200,201,202", "TGT: 200/201/202", "T1 380 T2 385 T3 390"
        targets = []
        
        # Strategy: First capture the section after TARGET keyword, then parse numbers from it
        # Pattern: Find "target/tgt/tp" followed by colon/dash, then capture everything until next keyword or newline
        target_section_match = re.search(
            r'(?:target|tgt|tp)s?\s*[:\s-]*([\d\s,./+]+?)(?=sl|stop|above|below|\n|$)',
            text,
            re.I
        )
        
        if target_section_match:
            # Extract all numbers from the captured section
            target_str = target_section_match.group(1)
            # Split by common delimiters: comma, slash, space, plus
            # Then extract numbers from each part
            potential_targets = re.findall(r'\d+(?:\.\d+)?', target_str)
            
            for t in potential_targets:
                try:
                    val = float(t)
                    price_val = float(data.get('price', 0))
                    sl_val = float(data.get('sl', 0))
                    
                    # Exclude if it equals Price or SL
                    # Also exclude small numbers that look like labels (1, 2, 3)
                    if val != price_val and val != sl_val and val > 5:
                        targets.append(t)
                except:
                    continue
        
        # Fallback: Try individual target patterns if section-based didn't work
        if not targets:
            # Pattern: "T1: 200" or "Target 1: 200"
            t_matches = re.findall(
                r'(?:target|tgt|tp|t)\s*(?:\d+)?\s*[:\s-]*[₹]?\s*(\d+(?:\.\d+)?)',
                text,
                re.I
            )
            
            for t in t_matches:
                try:
                    val = float(t)
                    price_val = float(data.get('price', 0))
                    sl_val = float(data.get('sl', 0))
                    
                    if val != price_val and val != sl_val and val > 5:
                        targets.append(t)
                except:
                    continue
        
        # Clean duplicates preserving order
        targets = list(dict.fromkeys(targets))
        
        # Set targets and determine final target
        if targets:
            data['targets'] = targets
            # Logic: If BUY, max is final target. If SELL, min is final target.
            try:
                nums = [float(x) for x in targets]
                if data.get('action') == 'SELL':
                    data['tgt'] = str(min(nums))
                else:
                    data['tgt'] = str(max(nums))
            except:
                data['tgt'] = targets[-1]
        
        return data


# Global instance
classifier = SignalClassifier()
