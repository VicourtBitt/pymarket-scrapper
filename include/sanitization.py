import re
import logging
from typing import Optional

class LocalizedSanitization:
    """
    Handles regex extraction, data cleaning, and type conversion.
    Can be configured per region (e.g., US vs Brazil number formats).
    """

    def __init__(self, decimal_separator: str = ".", thousands_separator: str = ",", currency_fallback: str = "") -> None:
        self.decimal_separator = decimal_separator
        self.thousands_separator = thousands_separator
        self.numeric_regex = re.compile(
            rf"[^\d\-{re.escape(self.decimal_separator)}{re.escape(self.thousands_separator)}]"
        )
        self.currency_regex = re.compile(r"([$€£¥₹₽¢₩₪₫฿]|R\$|[A-Z]{3})")
        self.default_currency_fallback = currency_fallback
        self.logger = logging.getLogger("sanitization")

    def parse_price(self, raw_price: str) -> float:
        """ Converts strings like '$1,234.50' or 'R$ 1.234,50' into a clean float. """
        if not raw_price:
            return 0.0

        # 1. Remove currency symbols, spaces, and letters using regex
        cleaned_str = self.numeric_regex.sub("", raw_price)
        # 2. Remove thousands separators
        cleaned_str = cleaned_str.replace(self.thousands_separator, "")
        # 3. Swap the localized decimal separator to a standard Python dot
        if self.decimal_separator != ".":
            cleaned_str = cleaned_str.replace(self.decimal_separator, ".")

        try:
            return float(cleaned_str)
        except ValueError:
            self.logger.warning(f"Warning: Could not parse price '{raw_price}'")
            return 0.0

    def extract_currency_symbol(self, raw_price: str) -> Optional[str]:
        """
        Extracts the currency symbol or code from a price string.
        Examples:
            '$1,234.50' -> '$'
            '100 USD' -> 'USD'
            'R$ 50,00' -> 'R$'
        """
        if not raw_price:
            return None

        match = self.currency_regex.search(raw_price)
        return match.group(1) if match else None

    def extract_vendor_id(self, url: str) -> Optional[str]:
        """ Example of another localized extraction: finding vendor IDs from URLs. """
        match = re.search(r"seller=([A-Z0-9]+)", url)
        return match.group(1) if match else None