import re
from typing import List, Dict

class RegexExtractor:
    """
    Declarative regex extractor. Pass in a dictionary mapping field names
    to regex patterns. It will return a dict of extracted lists.
    """

    def __init__(self, rules: Dict[str, str]):
        # Pre-compile the regexes for performance
        self.rules = {
            field: re.compile(pattern, re.IGNORECASE)
            for field, pattern in rules.items()
        }

    def extract(self, text: str) -> Dict[str, List[str]]:
        results = {}
        for field, pattern in self.rules.items():
            # Extract all matches and use set() to drop duplicate emails/phones
            matches = list(set(pattern.findall(text)))
            if matches:
                results[field] = matches
        return results