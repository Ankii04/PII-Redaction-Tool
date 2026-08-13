"""
fake_generator.py
-----------------
Generates consistent fake replacement values for detected PII entities.

Design:
  - FakeValueRegistry maintains a (entity_type, original_text) → fake_value dict
  - Same original PII always produces the same fake value within a run
  - Fake values are realistic (Indian context) but never contain real PII
  - No external dependencies — uses only stdlib + carefully chosen pools
"""

from __future__ import annotations

import re
from typing import Dict, Tuple


# ---------------------------------------------------------------------------
# Fake value pools
# ---------------------------------------------------------------------------

_FAKE_PERSONS = [
    ("Ananya", "Sharma"),   ("Vikram", "Mehta"),    ("Priya", "Nair"),
    ("Rohan", "Verma"),     ("Deepa", "Iyer"),       ("Arjun", "Patel"),
    ("Sneha", "Joshi"),     ("Rahul", "Gupta"),      ("Kavita", "Singh"),
    ("Amit", "Kumar"),      ("Pooja", "Rao"),         ("Suresh", "Reddy"),
    ("Meera", "Pillai"),    ("Kiran", "Bhat"),        ("Neha", "Desai"),
    ("Ajay", "Mishra"),     ("Sunita", "Tiwari"),    ("Rajiv", "Saxena"),
    ("Divya", "Pandey"),    ("Manoj", "Chauhan"),    ("Ravi", "Krishnan"),
    ("Lata", "Bhatt"),      ("Sanjay", "Malhotra"),  ("Geeta", "Agarwal"),
    ("Nikhil", "Bansal"),   ("Rekha", "Srivastava"), ("Vivek", "Chaudhary"),
    ("Asha", "Ghosh"),      ("Pramod", "Tripathi"),  ("Swati", "Das"),
]

_FAKE_EMAIL_DOMAINS = [
    "example.com", "sample.org", "testmail.in", "fakeemail.co.in",
    "demomail.com", "placeholder.in",
]

_FAKE_COMPANY_WORDS = [
    "Alpha", "Beta", "Delta", "Omega", "Apex", "Prime",
    "Unity", "Nova", "Zenith", "Sigma", "Crest", "Vega",
    "Orion", "Atlas", "Titan", "Nexus", "Vertex", "Horizon",
]

_FAKE_COMPANY_CATEGORIES = [
    "Technologies", "Solutions", "Industries", "Services",
    "Analytics", "Enterprises", "Holdings", "Ventures",
    "Consulting", "Systems",
]

_FAKE_STREETS = [
    "123, Sample Nagar", "456, Demo Colony", "789, Placeholder Road",
    "101, Example Lane", "202, Test Building, MG Road",
    "303, Model Society, FC Road",
]

_FAKE_CITIES = ["Pune", "Mumbai", "Bangalore", "Delhi", "Chennai"]
_FAKE_PINS   = [411001, 411045, 400001, 400051, 560001, 110001]

_FAKE_IPS = [f"203.0.113.{i}" for i in range(1, 100)]   # RFC 5737 documentation range


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class FakeValueRegistry:
    """
    Central registry: maps (entity_type, original_text) → fake_value.
    All lookups are in-memory; same key always returns the same fake value.
    """

    def __init__(self) -> None:
        self._mapping: Dict[Tuple[str, str], str] = {}
        self._counters: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_create(self, entity_type: str, original: str) -> str:
        """Return an existing fake value or create a new one."""
        key = (entity_type, original.strip())
        if key not in self._mapping:
            self._mapping[key] = self._generate(entity_type, original.strip())
        return self._mapping[key]

    def mapping_snapshot(self) -> Dict[Tuple[str, str], str]:
        """Return a read-only copy of the full mapping (for reporting)."""
        return dict(self._mapping)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_idx(self, entity_type: str) -> int:
        idx = self._counters.get(entity_type, 0)
        self._counters[entity_type] = idx + 1
        return idx

    def _generate(self, entity_type: str, original: str) -> str:
        idx = self._next_idx(entity_type)
        generators = {
            "PERSON":       self._fake_person,
            "EMAIL_ADDRESS": self._fake_email,
            "PHONE_NUMBER": self._fake_phone,
            "ORGANIZATION": self._fake_company,
            "ADDRESS":      self._fake_address,
            "IP_ADDRESS":   self._fake_ip,
            "US_SSN":       self._fake_ssn,
            "CREDIT_CARD":  self._fake_credit_card,
            "DATE_OF_BIRTH": self._fake_dob,
        }
        gen = generators.get(entity_type)
        if gen:
            return gen(idx, original)
        return f"[{entity_type}_{idx + 1}]"

    # ------------------------------------------------------------------
    # Per-type generators
    # ------------------------------------------------------------------

    def _fake_person(self, idx: int, original: str) -> str:
        first, last = _FAKE_PERSONS[idx % len(_FAKE_PERSONS)]
        # For indices beyond the pool, append a numeric suffix
        cycle = idx // len(_FAKE_PERSONS)
        suffix = f" {cycle + 1}" if cycle > 0 else ""
        return f"{first} {last}{suffix}"

    def _fake_email(self, idx: int, original: str) -> str:
        first, last = _FAKE_PERSONS[idx % len(_FAKE_PERSONS)]
        domain = _FAKE_EMAIL_DOMAINS[idx % len(_FAKE_EMAIL_DOMAINS)]
        return f"{first.lower()}.{last.lower()}@{domain}"

    def _fake_phone(self, idx: int, original: str) -> str:
        # Deterministic 10-digit Indian mobile starting with 9
        # Spread values across the number space
        seed = (9000000000 + idx * 13_337_777) % 10_000_000_000
        digits = str(seed).zfill(10)
        # Ensure starts with 9 (valid Indian mobile prefix)
        digits = "9" + digits[1:]
        return f"+91 {digits[:5]} {digits[5:]}"

    def _fake_company(self, idx: int, original: str) -> str:
        word = _FAKE_COMPANY_WORDS[idx % len(_FAKE_COMPANY_WORDS)]
        cat  = _FAKE_COMPANY_CATEGORIES[idx % len(_FAKE_COMPANY_CATEGORIES)]

        # Preserve the legal suffix type from the original
        orig_lower = original.lower()
        if re.search(r"\bllp\b", orig_lower):
            suffix = "LLP"
        elif re.search(r"\b(pvt\.?\s*ltd\.?|private\s+limited)\b", orig_lower):
            suffix = "Private Limited"
        elif re.search(r"\bpublic\s+limited\b", orig_lower):
            suffix = "Limited"
        elif re.search(r"\blimited\b", orig_lower):
            suffix = "Limited"
        elif re.search(r"\binc\.?\b", orig_lower):
            suffix = "Inc."
        elif re.search(r"\bcorp\.?\b", orig_lower):
            suffix = "Corp."
        else:
            suffix = "Private Limited"

        return f"{word} {cat} {suffix}"

    def _fake_address(self, idx: int, original: str) -> str:
        street = _FAKE_STREETS[idx % len(_FAKE_STREETS)]
        city   = _FAKE_CITIES[idx % len(_FAKE_CITIES)]
        pin    = _FAKE_PINS[idx % len(_FAKE_PINS)]
        return f"{street}, {city} \u2013 {pin}, Maharashtra, India"

    def _fake_ip(self, idx: int, original: str) -> str:
        return _FAKE_IPS[idx % len(_FAKE_IPS)]

    def _fake_ssn(self, idx: int, original: str) -> str:
        n = (100_000_000 + idx * 123_456_789) % 1_000_000_000
        s = str(n).zfill(9)
        return f"{s[:3]}-{s[3:5]}-{s[5:]}"

    def _fake_credit_card(self, idx: int, original: str) -> str:
        """Generate a Luhn-valid Visa-style 16-digit card number."""
        # Start with 4 (Visa) + 12 varying digits, compute check digit
        base = list(f"4{'0' * 14}{idx % 10}")
        # Fill middle with deterministic digits
        for i in range(1, 15):
            base[i] = str((idx * (i + 3) + 7) % 10)
        # Compute Luhn check digit
        total = 0
        for i, d in enumerate(base[:-1]):
            n = int(d)
            if (13 - i) % 2 == 1:
                n *= 2
                if n > 9:
                    n -= 9
            total += n
        base[-1] = str((10 - total % 10) % 10)
        num = "".join(base)
        return f"{num[:4]} {num[4:8]} {num[8:12]} {num[12:]}"

    def _fake_dob(self, idx: int, original: str) -> str:
        """Shift any year found in the DOB by -10 years."""
        result = re.sub(
            r"\b(19|20)(\d{2})\b",
            lambda m: str(int(m.group(0)) - 10),
            original,
        )
        return result if result != original else "01/01/1980"
