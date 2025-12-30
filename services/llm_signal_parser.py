"""
LLM-based Signal Parser using Google Gemini Flash (Free Tier)

This module uses Google's Gemini Flash model to intelligently parse
trading signals from Telegram messages, replacing rigid regex patterns
with natural language understanding.

Free Tier Limits: 15 requests/minute, 1M tokens/day
"""

import os
import json
import logging
from typing import Dict, Optional
from utils.logging import get_logger

logger = get_logger(__name__)

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logger.warning("google-generativeai not installed. LLM parsing will be disabled.")


class LLMSignalParser:
    """Intelligent signal parser using Gemini Flash"""
    
    def __init__(self):
        self.enabled = False
        self.model = None
        
        if not GENAI_AVAILABLE:
            logger.warning("GenAI library not available")
            return
            
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not found in .env. LLM parsing disabled.")
            return
            
        # Configure Gemini with free tier model
        try:
            genai.configure(api_key=api_key)
            # Use Gemini 1.5 Flash-8B - newest free tier model
            # Must use full path format for newer models
            self.model = genai.GenerativeModel('models/gemini-1.5-flash-8b')
            self.enabled = True
            logger.info("LLM Signal Parser initialized successfully with Gemini 1.5 Flash-8B")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini: {e}")
    
    def parse_signal(self, text: str) -> Dict[str, any]:
        """
        Parse trading signal from text using LLM
        
        Args:
            text: Raw message text from Telegram
            
        Returns:
            dict with keys:
                - is_signal (bool): Whether this is a trading signal
                - action (str): BUY or SELL
                - symbol (str): Trading symbol
                - strike (str): Strike price for options
                - option_type (str): CE or PE
                - price (float): Entry price
                - sl (float): Stop loss
                - tgt (float): Target
                - confidence (float): 0-1 confidence score
        """
        if not self.enabled:
            return {"is_signal": False, "error": "LLM parser not available"}
        
        try:
            prompt = f"""You are a trading signal parser. Analyze this message and determine if it contains a trading signal.

Message: "{text}"

Return ONLY a JSON object with these fields (no markdown, no extra text):
{{
  "is_signal": true/false,
  "action": "BUY" or "SELL" (if is_signal is true),
  "symbol": "symbol name" (e.g., "NIFTY", "BANKNIFTY"),
  "strike": "strike price as string",
  "option_type": "CE" or "PE",
  "price": entry price as number (See rules below),
  "sl": stop loss as number (null if not mentioned),
  "tgt": first target as number (null if not mentioned),
  "targets": [list of all targets found as numbers],
  "confidence": 0.0 to 1.0
}}

RULES:
1. Entry Price specific: If a range is given like "370-390" or "above 370-390", ALWAYS select the LOWER BOUND (e.g., 370) as the 'price'. Valid entry is specific point or lower bound of range.
2. Targets: Parse multiple targets separated by dashes ("410-420-430") or spaces. Return all in "targets" array.
3. Stop Loss: If missing, set "sl" to null.

examples:
- "SENSEX 85400 PE above 370-390 Target- 410-420-430" → {{"is_signal": true, "symbol": "SENSEX", "strike": "85400", "option_type": "PE", "price": 370, "targets": [410, 420, 430], "sl": None, "action": "BUY"}}
- "BUY NIFTY 22000 CE @ 150 SL 120 TGT 200" → {{"is_signal": true, "price": 150, "sl": 120, "targets": [200]}}

Return ONLY the JSON."""

            response = self.model.generate_content(
                prompt,
                generation_config={
                    'temperature': 0.1,  # Low temperature for consistent parsing
                    'top_p': 0.95,
                    'max_output_tokens': 256,
                }
            )
            
            # Extract and parse JSON from response
            result_text = response.text.strip()
            
            # Remove markdown code blocks if present
            if result_text.startswith('```'):
                result_text = result_text.split('```')[1]
                if result_text.startswith('json'):
                    result_text = result_text[4:]
                result_text = result_text.strip()
            
            result = json.loads(result_text)
            
            logger.info(f"LLM parsed signal (confidence: {result.get('confidence', 0)}): {result}")
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}. Response: {response.text if 'response' in locals() else 'N/A'}")
            return {"is_signal": False, "error": "JSON parse error"}
        except Exception as e:
            logger.error(f"LLM parsing error: {e}")
            return {"is_signal": False, "error": str(e)}


# Global instance
llm_parser = LLMSignalParser()
