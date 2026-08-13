"""
recognizers.py
--------------
All custom Presidio recognizers for the PII Redaction Tool.

Recognizers:
    - IndianPhoneRecognizer   : regex + context for Indian phone formats
    - SSNStrictRecognizer     : strict SSN pattern with optional context
    - DOBRecognizer           : context-gated date-of-birth promoter
    - CompanyNameRecognizer   : 3-layer gate (NER ORG + suffix + FP suppression)
    - AddressRecognizer       : multi-signal multi-line address detection
"""

from __future__ import annotations

import re
import logging
from typing import List, Optional

from presidio_analyzer import (
    PatternRecognizer,
    Pattern,
    RecognizerResult,
    AnalysisExplanation,
)
from presidio_analyzer.nlp_engine import NlpArtifacts

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Indian Phone Recognizer
# ---------------------------------------------------------------------------

_INDIAN_PHONE_PATTERNS = [
    # +91 XX XXXX XXXX  or  +91-XX-XXXX-XXXX
    r"\+91[\s\-]?\d{2}[\s\-]?\d{4}[\s\-]?\d{4}",
    # +91 XXXXX XXXXX  (mobile)
    r"\+91[\s\-]?\d{5}[\s\-]?\d{5}",
    # 0XX-XXXXXXXX  or  0XX 4509 4400  or 0XX-4509-4400
    r"0\d{2,4}[\s\-]?\d{3,4}[\s\-]?\d{4}",
    # +91 XXXXXXXXXX  (10 digit mobile after country code)
    r"\+91[\s\-]?\d{10}",
]

_INDIAN_PHONE_CONTEXT = [
    "phone", "tel", "telephone", "mobile", "fax", "contact",
    "call", "helpline", "number", "no.", "nos.",
]

_COMBINED_PHONE_RE = re.compile(
    r"(?:" + "|".join(_INDIAN_PHONE_PATTERNS) + r")",
    re.IGNORECASE,
)


class IndianPhoneRecognizer(PatternRecognizer):
    """Detects Indian phone numbers (+91 formats and 0XX-prefix formats)."""

    ENTITY = "PHONE_NUMBER"

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="indian_phone",
                regex=r"(?:" + "|".join(_INDIAN_PHONE_PATTERNS) + r")",
                score=0.75,
            )
        ]
        super().__init__(
            supported_entity=self.ENTITY,
            patterns=patterns,
            context=_INDIAN_PHONE_CONTEXT,
            name="IndianPhoneRecognizer",
        )


# ---------------------------------------------------------------------------
# 2. Strict SSN Recognizer
# ---------------------------------------------------------------------------

_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_SSN_CONTEXT = [
    "ssn", "social security", "social security number", "ss#", "ss #",
    "tax id", "taxpayer id",
]


class SSNStrictRecognizer(PatternRecognizer):
    """Strict SSN: requires 'NNN-NN-NNNN' with hyphens. No bare 9-digit numbers."""

    ENTITY = "US_SSN"

    def __init__(self) -> None:
        patterns = [Pattern(name="ssn_strict", regex=r"\b\d{3}-\d{2}-\d{4}\b", score=0.85)]
        super().__init__(
            supported_entity=self.ENTITY,
            patterns=patterns,
            context=_SSN_CONTEXT,
            name="SSNStrictRecognizer",
        )


# ---------------------------------------------------------------------------
# 3. DOB Recognizer  (context-gated)
# ---------------------------------------------------------------------------

# Anchor: context phrases that indicate a date is a date-of-birth
_DOB_CONTEXT_RE = re.compile(
    r"\b(dob|date\s+of\s+birth|birth\s+date|born\s+on|born|d\.o\.b\.?)\s*[:\-–]?\s*",
    re.IGNORECASE,
)

# Common date formats
_DATE_PATTERNS = [
    r"\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}",   # DD/MM/YYYY  DD-MM-YY
    r"\d{1,2}\s+\w+\s+\d{4}",                      # 15 August 1985
    r"\w+\s+\d{1,2},?\s+\d{4}",                    # August 15, 1985
]
_DATE_RE = re.compile(
    r"(?:" + "|".join(_DATE_PATTERNS) + r")",
    re.IGNORECASE,
)

# Window (characters) before a date to look for DOB context
_DOB_LOOK_BACK = 60


class DOBRecognizer(PatternRecognizer):
    """
    Promotes a DATE_TIME result to DATE_OF_BIRTH only when a DOB-context phrase
    appears within _DOB_LOOK_BACK characters before the date.

    Implemented as a PatternRecognizer that finds date patterns and then checks
    context manually in analyze().
    """

    ENTITY = "DATE_OF_BIRTH"

    def __init__(self) -> None:
        patterns = [
            Pattern(name="dob_date", regex=p, score=0.9)
            for p in _DATE_PATTERNS
        ]
        super().__init__(
            supported_entity=self.ENTITY,
            patterns=patterns,
            name="DOBRecognizer",
        )

    def analyze(self, text: str, entities: List[str], nlp_artifacts: Optional[NlpArtifacts] = None) -> List[RecognizerResult]:
        results = super().analyze(text, entities, nlp_artifacts)
        verified = []
        for r in results:
            # Only keep if DOB context precedes the match
            window_start = max(0, r.start - _DOB_LOOK_BACK)
            preceding = text[window_start:r.start]
            if _DOB_CONTEXT_RE.search(preceding):
                verified.append(r)
        return verified


# ---------------------------------------------------------------------------
# 4. Company Name Recognizer  (3-layer gate)
# ---------------------------------------------------------------------------

# Layer 2: Company suffixes that must appear as proper suffixes (not standalone words)
_COMPANY_SUFFIX_RE = re.compile(
    r"(?:[\u2018\u2019\u201c\u201d\"\'\(]?\b[A-Z][A-Za-z0-9\'-]*(?:\s+(?:&|[A-Z0-9][A-Za-z0-9\'-]*)){0,8}"
    r"\s+(?:Private\s+Limited|Pvt\.?\s*Ltd\.?|Public\s+Limited|Limited|LLP|Corporation|Corp\.?|Incorporated|Inc\.?|Holdings|Securities|Technologies|Solutions|Services|Infrastructure|Industries|Enterprises|Investments|Finance)\b[\u2018\u2019\u201c\u201d\"\'\)]?)",
    re.IGNORECASE,
)

# Layer 3: FP suppression — generic references that look like companies but are not
_GENERIC_COMPANY_RE = re.compile(
    r"^(the|our|this|such|any|said|a|an)\s+"
    r"(company|bank|corporation|trust|fund|enterprise|organisation|organization|institution)\s*$",
    re.IGNORECASE,
)

# Also suppress pure suffix words without a proper name prefix
_BARE_SUFFIX_RE = re.compile(
    r"^(private\s+limited|pvt\.?\s*ltd\.?|llp|limited|corporation|inc\.?|"
    r"trust|fund|bank|securities)\s*$",
    re.IGNORECASE,
)


class CompanyNameRecognizer(PatternRecognizer):
    """
    3-layer gate:
      1. Regex match on company suffix patterns (including quoted names)
      2. Candidate must have a proper name prefix (not a bare suffix)
      3. Generic references ('the Company', 'our Bank') are suppressed
    """

    ENTITY = "ORGANIZATION"

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="company_suffix",
                regex=(
                    r"(?:[\u2018\u2019\u201c\u201d\"\'\(]?\b[A-Z][A-Za-z0-9\'-]*(?:\s+(?:&|[A-Z0-9][A-Za-z0-9\'-]*)){0,8}"
                    r"\s+(?:Private\s+Limited|Pvt\.?\s*Ltd\.?|Public\s+Limited|Limited|LLP|Corporation|Corp\.?|Incorporated|Inc\.?|Holdings|Securities|Technologies|Solutions|Services|Infrastructure|Industries|Enterprises|Investments|Finance)\b[\u2018\u2019\u201c\u201d\"\'\)]?)"
                ),
                score=0.85,
            )
        ]
        super().__init__(
            supported_entity=self.ENTITY,
            patterns=patterns,
            name="CompanyNameRecognizer",
        )

    def analyze(self, text: str, entities: List[str], nlp_artifacts: Optional[NlpArtifacts] = None) -> List[RecognizerResult]:
        results = super().analyze(text, entities, nlp_artifacts)
        filtered = []
        for r in results:
            span = text[r.start:r.end].strip(" \t\n\r\u2018\u2019\u201c\u201d\"'()")
            # Layer 3: suppress generic references
            if _GENERIC_COMPANY_RE.match(span):
                logger.debug("CompanyRecognizer: suppressed generic ref '%s'", span)
                continue
            # Layer 3: suppress bare suffixes
            if _BARE_SUFFIX_RE.match(span):
                logger.debug("CompanyRecognizer: suppressed bare suffix '%s'", span)
                continue
            filtered.append(r)
        return filtered


# ---------------------------------------------------------------------------
# 5. Context-Aware Person Recognizer
# ---------------------------------------------------------------------------

_PERSON_CONTEXT_RE = re.compile(
    r"(?:(?:Contact\s+Person|Director|Promoter|Secretary|Officer|Auditor|Executive|Manager|Partner|CFO|CEO|MD|CMD|Name)\s*[:\-]\s*|(?:Mr\.|Ms\.|Mrs\.|Dr\.|Shri|Smt\.?)\s+)"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})"
)


class ContextPersonRecognizer(PatternRecognizer):
    """
    Detects dynamic person names supported by strong business/honorific context:
      - 'Contact Person: Sarthak Malvadkar'
      - 'Managing Director: Priya Singh'
      - 'Mr. Rajesh Kumar', 'Ms. Sneha Sharma'
    """

    ENTITY = "PERSON"

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="person_context_anchor",
                regex=r"(?:Mr\.|Ms\.|Mrs\.|Dr\.)\s+[A-Z][a-z]+",
                score=0.90,
            )
        ]
        super().__init__(
            supported_entity=self.ENTITY,
            patterns=patterns,
            name="ContextPersonRecognizer",
        )

    def analyze(self, text: str, entities: List[str], nlp_artifacts: Optional[NlpArtifacts] = None) -> List[RecognizerResult]:
        results = []
        for match in _PERSON_CONTEXT_RE.finditer(text):
            # Capture the name group (group 1)
            name_span = match.group(1)
            name_start = match.start(1)
            name_end = match.end(1)

            results.append(RecognizerResult(
                entity_type=self.ENTITY,
                start=name_start,
                end=name_end,
                score=0.90,
                analysis_explanation=AnalysisExplanation(
                    recognizer=self.name,
                    original_score=0.90,
                    textual_explanation=f"Person name detected with context anchor: '{text[match.start():name_start].strip()}'"
                )
            ))
        return results


# ---------------------------------------------------------------------------
# 6. Address Recognizer  (multi-signal, multi-line aware)
# ---------------------------------------------------------------------------

# Anchor signals
_PIN_CODE_RE = re.compile(r"\b[1-9][0-9]{5}\b")

_ADDRESS_KEYWORDS = re.compile(
    r"\b(floor|building|bldg|plot|road|street|lane|avenue|nagar|colony|sector"
    r"|apartment|apt|complex|village|taluka|taluqa|district|dist\.?"
    r"|registered\s+office|corporate\s+office|correspondence\s+address"
    r"|head\s+office|branch\s+office|flat|wing|block|phase|survey\s+no"
    r"|s\.no|plot\s+no|door\s+no|house\s+no|gat\s+no|shop\s+no)\b",
    re.IGNORECASE,
)

_ADDRESS_CONTEXT_BOOST = re.compile(
    r"\b(registered\s+office|corporate\s+office|correspondence\s+address"
    r"|head\s+office|branch\s+office|mailing\s+address|office\s+address"
    r"|contact\s+address)\s*(?::\s*|\s+at\s+)",
    re.IGNORECASE,
)

# Indian states and major cities as GPE hints
_INDIA_GPE = re.compile(
    r"\b(maharashtra|karnataka|gujarat|delhi|tamil\s*nadu|telangana|rajasthan"
    r"|uttar\s*pradesh|west\s*bengal|pune|mumbai|bengaluru|bangalore|hyderabad"
    r"|chennai|kolkata|ahmedabad|surat|jaipur|lucknow|nagpur|thane|nashik"
    r"|aurangabad|solapur|amravati|navi\s*mumbai)\b",
    re.IGNORECASE,
)


class AddressRecognizer(PatternRecognizer):
    """
    Multi-signal address detector:
      - Anchor: PIN code | address keyword | India GPE
      - Expansion: extend span to capture multi-line address (up to 3 lines)
      - Context boost: 'Address:', 'Registered Office:' etc. raise confidence
      - A single city name alone does NOT trigger an ADDRESS result.
    """

    ENTITY = "ADDRESS"
    EXPANSION_WINDOW = 200  # chars to look around anchor

    def __init__(self) -> None:
        # Use PIN code as the primary pattern anchor
        patterns = [
            Pattern(
                name="pin_code_anchor",
                regex=r"\b[1-9][0-9]{5}\b",
                score=0.50,  # Low initial score; boosted by surrounding signals
            )
        ]
        super().__init__(
            supported_entity=self.ENTITY,
            patterns=patterns,
            name="AddressRecognizer",
        )

    def analyze(self, text: str, entities: List[str], nlp_artifacts: Optional[NlpArtifacts] = None) -> List[RecognizerResult]:
        results = []

        # Find all PIN code anchors
        for m in _PIN_CODE_RE.finditer(text):
            pin_start = m.start()
            pin_end = m.end()
            # Look in a window around the PIN
            win_start = max(0, pin_start - self.EXPANSION_WINDOW)
            win_end = min(len(text), pin_end + self.EXPANSION_WINDOW)
            window = text[win_start:win_end]

            score = 0.50
            has_keyword = bool(_ADDRESS_KEYWORDS.search(window))
            has_gpe = bool(_INDIA_GPE.search(window))
            has_context = bool(_ADDRESS_CONTEXT_BOOST.search(text[max(0, pin_start - 120):pin_start]))

            if has_keyword:
                score += 0.15
            if has_gpe:
                score += 0.10
            if has_context:
                score += 0.20

            # Require at least one additional signal beyond PIN alone
            if not (has_keyword or has_gpe or has_context):
                continue

            # Expand span leftward to start of address block
            span_start = self._find_address_start(text, pin_start, win_start)
            span_end = self._find_address_end(text, pin_end, win_end)

            results.append(RecognizerResult(
                entity_type=self.ENTITY,
                start=span_start,
                end=span_end,
                score=min(score, 0.95),
                analysis_explanation=AnalysisExplanation(
                    recognizer=self.name,
                    original_score=score,
                    textual_explanation=(
                        f"PIN={bool(m)}, keyword={has_keyword}, "
                        f"gpe={has_gpe}, ctx={has_context}"
                    ),
                ),
            ))

        # Also find keyword-anchored addresses (no PIN) when context is present
        for m in _ADDRESS_CONTEXT_BOOST.finditer(text):
            ctx_end = m.end()
            # Look ahead for address content
            ahead = text[ctx_end:min(len(text), ctx_end + 300)]
            if _ADDRESS_KEYWORDS.search(ahead) or _INDIA_GPE.search(ahead) or _PIN_CODE_RE.search(ahead):
                span_end = self._find_address_end(text, ctx_end, min(len(text), ctx_end + 300))
                results.append(RecognizerResult(
                    entity_type=self.ENTITY,
                    start=m.start(),
                    end=span_end,
                    score=0.70,
                    analysis_explanation=AnalysisExplanation(
                        recognizer=self.name,
                        original_score=0.70,
                        textual_explanation="context-anchored address",
                    ),
                ))

        # Deduplicate overlapping address results (keep highest score)
        return self._deduplicate(results)

    @staticmethod
    def _find_address_start(text: str, anchor: int, floor: int) -> int:
        """Walk leftward from anchor to the start of the address block."""
        # Find the last newline or address context keyword before anchor
        segment = text[floor:anchor]
        # Look for last newline
        nl = segment.rfind("\n")
        if nl != -1:
            return floor + nl + 1
        return floor

    @staticmethod
    def _find_address_end(text: str, anchor: int, ceiling: int) -> int:
        """Walk rightward from anchor to the end of the address block."""
        segment = text[anchor:ceiling]
        # Look for double newline (paragraph break)
        dbl_nl = segment.find("\n\n")
        if dbl_nl != -1:
            return anchor + dbl_nl
        return min(len(text), ceiling)

    @staticmethod
    def _deduplicate(results: List[RecognizerResult]) -> List[RecognizerResult]:
        """Remove fully-contained lower-scoring spans."""
        results.sort(key=lambda r: r.score, reverse=True)
        kept = []
        for r in results:
            dominated = any(
                k.start <= r.start and k.end >= r.end and k is not r
                for k in kept
            )
            if not dominated:
                kept.append(r)
        return kept
