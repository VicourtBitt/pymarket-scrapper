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
            # Whole-match strings (even with capture groups), deduplicated
            # in first-seen order so ETL output is deterministic.
            matches = list(dict.fromkeys(m.group(0) for m in pattern.finditer(text)))
            if matches:
                results[field] = matches
        return results