"""
redactor.py
-----------
Core Presidio pipeline:
  1. Build AnalyzerEngine with built-in + custom recognizers
  2. Analyze a text unit to get RecognizerResult list
  3. Resolve overlapping entities using priority hierarchy
  4. Filter by per-type confidence thresholds
  5. Anonymize text using type-specific replacement labels
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple


from presidio_analyzer import AnalyzerEngine, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from recognizers import (
    IndianPhoneRecognizer,
    SSNStrictRecognizer,
    DOBRecognizer,
    CompanyNameRecognizer,
    AddressRecognizer,
    ContextPersonRecognizer,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global FP suppression for ORGANIZATION
# ---------------------------------------------------------------------------

# Generic words that spaCy NER frequently mis-tags as ORG
_ORG_FP_EXACT = re.compile(
    r"^(the\s+)?(company|bank|corporation|trust|fund|enterprise|organisation"
    r"|organization|institution|group|committee|authority|board|sebi|nse|bse"
    r"|ipo|rbi|roc|mca|cin|din|pan|tan|gst|ssn|ceo|cfo|coo|md|cmd|llp|ltd"
    r"|pvt|inc|corp|co\.|co)\s*\.?$",
    re.IGNORECASE,
)


# Words/verbs that indicate a phrase is a sentence fragment, not a company name
_FRAGMENT_VERBS = {
    "was", "were", "is", "are", "been", "being", "have", "has", "had",
    "originally", "incorporated", "registered", "pursuant", "provisions",
    "section", "clause", "regulation", "regulations", "under", "against",
    "repetition", "holding", "allotted", "transferred", "shifted", "situated",
}

_GENERIC_ORG_PREFIX = re.compile(
    r"^(our|the|this|such|any|said)\s+(company|bank|board|committee|issuer|promoter|trust)",
    re.IGNORECASE,
)


def _is_org_fp(text: str) -> bool:
    """Return True if the text is a known generic ORGANIZATION false positive or sentence fragment."""
    stripped = text.strip(" \t\n\r\u2018\u2019\u201c\u201d\"'()")
    
    # Check if phrase starts with generic reference ("Our Company...", "The Bank...")
    if _GENERIC_ORG_PREFIX.match(stripped):
        # Only allow if it contains a genuine legal suffix at the end (e.g., "Our Company ABC Ltd")
        if not re.search(r"\b(Private\s+Limited|Pvt\.?\s*Ltd\.?|Limited|LLP|Inc\.?|Corp\.?)\b", stripped, re.I):
            return True

    # Single-token all-caps acronym (≤5 chars) that aren't company names
    if re.fullmatch(r"[A-Z]{1,5}\.?", stripped):
        known_label_acronyms = {"SSN", "CEO", "CFO", "COO", "MD", "CMD", "MCA",
                                 "RBI", "ROC", "CIN", "DIN", "PAN", "TAN",
                                 "GST", "IPO", "NSE", "BSE", "SEBI", "SCRR",
                                 "ICDR", "SCRA", "FEMA", "IFRS", "KMP", "KMPS", "WTD"}
        if stripped.rstrip(".") in known_label_acronyms:
            return True

    # Exact generic match
    if bool(_ORG_FP_EXACT.match(stripped)):
        return True

    # Sentence fragment check: if contains lowercase grammatical verbs
    # BUT exempt spans that END in a legal company suffix — spaCy may grab leading
    # sentence words yet the entity is still a genuine company name.
    _LEGAL_SUFFIX_END = re.compile(
        r"\b(Private\s+Limited|Pvt\.?\s*Ltd\.?|Public\s+Limited|Limited|LLP|"
        r"Corporation|Corp\.?|Incorporated|Inc\.?|Holdings|Technologies|Solutions|"
        r"Services|Industries|Enterprises|Investments|Finance|Securities)\s*\.?$",
        re.IGNORECASE,
    )
    if not _LEGAL_SUFFIX_END.search(stripped):
        words = [w.lower() for w in re.findall(r"\b[a-z]+\b", stripped)]
        if any(w in _FRAGMENT_VERBS for w in words):
            return True

    return False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Type-specific replacement labels  (centralised — strictly 9 required PII types)
ENTITY_LABEL_MAP: Dict[str, str] = {
    "PERSON":           "[REDACTED: PERSON_NAME]",
    "EMAIL_ADDRESS":    "[REDACTED: EMAIL]",
    "PHONE_NUMBER":     "[REDACTED: PHONE]",
    "ORGANIZATION":     "[REDACTED: COMPANY_NAME]",
    "ADDRESS":          "[REDACTED: ADDRESS]",
    "US_SSN":           "[REDACTED: SSN]",
    "CREDIT_CARD":      "[REDACTED: CREDIT_CARD]",
    "DATE_OF_BIRTH":    "[REDACTED: DOB]",
    "IP_ADDRESS":       "[REDACTED: IP_ADDRESS]",
}

# Per-type confidence thresholds
CONFIDENCE_THRESHOLDS: Dict[str, float] = {
    "EMAIL_ADDRESS":  0.50,
    "PHONE_NUMBER":   0.60,
    "PERSON":         0.70,
    "ORGANIZATION":   0.75,
    "ADDRESS":        0.65,
    "US_SSN":         0.85,
    "CREDIT_CARD":    0.80,
    "DATE_OF_BIRTH":  0.90,
    "IP_ADDRESS":     0.60,
}

DEFAULT_THRESHOLD = 0.70

# Entity priority for overlap resolution (lower number = higher priority)
ENTITY_PRIORITY: Dict[str, int] = {
    "DATE_OF_BIRTH":  1,
    "CREDIT_CARD":    1,
    "US_SSN":         1,
    "ADDRESS":        2,
    "EMAIL_ADDRESS":  3,
    "PHONE_NUMBER":   3,
    "IP_ADDRESS":     3,
    "PERSON":         4,
    "ORGANIZATION":   4,
    "DATE_TIME":      5,
    "LOCATION":       5,
    "NRP":            5,
}

SUPPORTED_ENTITIES = list(ENTITY_LABEL_MAP.keys())

# ---------------------------------------------------------------------------
# spaCy model selection (non-blocking)
# ---------------------------------------------------------------------------

def _select_spacy_model() -> str:
    """Return the best available spaCy model; never blocks execution."""
    import spacy
    preference = ["en_core_web_lg", "en_core_web_md", "en_core_web_sm"]
    for model in preference:
        if spacy.util.is_package(model):
            logger.info("Using spaCy model: %s", model)
            return model
    raise RuntimeError(
        "No compatible spaCy model found. Install one with:\n"
        "  python -m spacy download en_core_web_lg\n"
        "  (or en_core_web_md / en_core_web_sm)"
    )


# ---------------------------------------------------------------------------
# Engine construction
# ---------------------------------------------------------------------------

def build_analyzer(spacy_model: Optional[str] = None) -> AnalyzerEngine:
    """
    Build a Presidio AnalyzerEngine with:
      - spaCy NLP engine (best available model)
      - All Presidio built-in recognizers
      - All custom recognizers
    """
    model_name = spacy_model or _select_spacy_model()
    logger.info("Building AnalyzerEngine with model '%s'", model_name)

    nlp_config = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": model_name}],
    }
    provider = NlpEngineProvider(nlp_configuration=nlp_config)
    nlp_engine = provider.create_engine()

    engine = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])

    # Register custom recognizers
    for recognizer_cls in [
        IndianPhoneRecognizer,
        SSNStrictRecognizer,
        DOBRecognizer,
        CompanyNameRecognizer,
        AddressRecognizer,
        ContextPersonRecognizer,
    ]:
        engine.registry.add_recognizer(recognizer_cls())
        logger.debug("Registered recognizer: %s", recognizer_cls.__name__)

    return engine


def build_anonymizer() -> AnonymizerEngine:
    return AnonymizerEngine()


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_text(
    analyzer: AnalyzerEngine,
    text: str,
    language: str = "en",
) -> List[RecognizerResult]:
    """Run Presidio analyzer on text; return raw results."""
    if not text or not text.strip():
        return []
    try:
        results = analyzer.analyze(
            text=text,
            language=language,
            entities=None,  # detect all supported entities
            score_threshold=0.0,  # we apply thresholds ourselves
        )
        return results
    except Exception as exc:
        logger.warning("Analyzer error on text snippet: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Overlap resolution
# ---------------------------------------------------------------------------

def resolve_overlaps(results: List[RecognizerResult]) -> List[RecognizerResult]:
    """
    Resolve overlapping RecognizerResults using:
      1. Entity priority (lower number wins)
      2. Span length (longer wins if same priority)
      3. Confidence score (higher wins if same priority + length)

    Returns a clean, non-overlapping list sorted by start offset (ascending).
    """
    if not results:
        return []

    def sort_key(r: RecognizerResult) -> Tuple:
        priority = ENTITY_PRIORITY.get(r.entity_type, 99)
        span_len = r.end - r.start
        return (priority, -span_len, -r.score)

    # Sort: best candidates first
    candidates = sorted(results, key=sort_key)
    kept: List[RecognizerResult] = []

    for candidate in candidates:
        overlaps = any(
            not (candidate.end <= kept_r.start or candidate.start >= kept_r.end)
            for kept_r in kept
        )
        if not overlaps:
            kept.append(candidate)
        else:
            logger.debug(
                "Dropped overlapping %s [%d-%d] score=%.2f",
                candidate.entity_type, candidate.start, candidate.end, candidate.score
            )

    # Sort by start for output
    kept.sort(key=lambda r: r.start)
    return kept


# ---------------------------------------------------------------------------
# Confidence filtering
# ---------------------------------------------------------------------------

def filter_by_threshold(
    results: List[RecognizerResult],
    text: str = "",
) -> List[RecognizerResult]:
    """
    Remove results below per-type confidence thresholds.
    Also suppresses generic ORGANIZATION false positives (spaCy NER artefacts).
    """
    filtered = []
    for r in results:
        # Only keep entity types configured for redaction
        if r.entity_type not in ENTITY_LABEL_MAP:
            continue

        # Suppress known ORGANIZATION false positives regardless of score
        if r.entity_type == "ORGANIZATION" and text:
            span = text[r.start:r.end]
            if _is_org_fp(span):
                logger.debug(
                    "Suppressed ORG FP '%s' [%d-%d]", span, r.start, r.end
                )
                continue

        threshold = CONFIDENCE_THRESHOLDS.get(r.entity_type, DEFAULT_THRESHOLD)
        if r.score >= threshold:
            filtered.append(r)
        else:
            logger.debug(
                "Filtered %s [%d-%d] score=%.2f < threshold=%.2f",
                r.entity_type, r.start, r.end, r.score, threshold
            )
    return filtered


# ---------------------------------------------------------------------------
# Anonymization
# ---------------------------------------------------------------------------

def build_operator_config() -> Dict[str, OperatorConfig]:
    """Build per-entity-type replace operators using ENTITY_LABEL_MAP."""
    return {
        entity_type: OperatorConfig("replace", {"new_value": label})
        for entity_type, label in ENTITY_LABEL_MAP.items()
    }


def anonymize_text(
    anonymizer: AnonymizerEngine,
    text: str,
    results: List[RecognizerResult],
    operators: Dict[str, OperatorConfig],
) -> str:
    """Apply Presidio anonymization and return redacted text."""
    if not results:
        return text
    try:
        result = anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators=operators,
        )
        return result.text
    except Exception as exc:
        logger.warning("Anonymizer error: %s", exc)
        return text


# ---------------------------------------------------------------------------
# High-level: process one text string end-to-end
# ---------------------------------------------------------------------------

def process_text(
    analyzer: AnalyzerEngine,
    anonymizer: AnonymizerEngine,
    operators: Dict[str, OperatorConfig],
    text: str,
) -> Tuple[str, List[RecognizerResult]]:
    """
    Full pipeline for a single text string:
      analyze → resolve overlaps → filter → anonymize

    Returns (redacted_text, kept_results).
    kept_results are sorted by start offset DESCENDING for safe right-to-left
    run-level redaction in docx_processor.apply_redactions().
    """
    raw = analyze_text(analyzer, text)
    filtered = filter_by_threshold(raw, text=text)
    resolved = resolve_overlaps(filtered)

    redacted = anonymize_text(anonymizer, text, resolved, operators)

    # Sort descending for offset-safe run surgery
    resolved_desc = sorted(resolved, key=lambda r: r.start, reverse=True)

    return redacted, resolved_desc
