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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    r"|pvt|inc|corp|co\.|co"
    r"|goods\s+and\s+services|goods\s+&\s+services"
    r"|securities|securities\s+law|capital\s+market"
    r"|reserve\s+bank|stock\s+exchange"
    r")\s*\.?$",
    re.IGNORECASE,
)

# Additional boilerplate phrases that start with uppercase but are NOT company names
_ORG_FP_PHRASES = re.compile(
    r"^("
    r"weighted\s+average\s+price"
    r"|details\s+of\s+price"
    r"|exemption\s+from"
    r"|on\s+the\s+conversion"
    r"|as\s+certified\s+by\b"
    r"|while\s+we\s+"
    r"|though\s+we\s+"
    r"|we\s+(require|will|meet|perform|maintain|strive|intend|propose|expect)"
    r"|company\s+and\s+all"
    r")",
    re.IGNORECASE,
)


# Words/verbs that indicate a phrase is a sentence fragment, not a company name
_FRAGMENT_VERBS = {
    "was", "were", "is", "are", "been", "being", "have", "has", "had",
    "originally", "incorporated", "registered", "pursuant", "provisions",
    "section", "clause", "regulation", "regulations", "under", "against",
    "repetition", "holding", "allotted", "transferred", "shifted", "situated",
    # Additional financial document boilerplate verbs
    "require", "requires", "required", "perform", "performs", "performed",
    "strive", "strives", "meet", "meets", "maintain", "maintains", "finance",
    "weighted", "complying", "certified", "conversion", "constitute",
    "include", "includes", "including", "affect", "affects", "protect",
    "invest", "propose", "intend", "intends", "expect", "expects",
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

    # Boilerplate phrase patterns (financial prospectus sentences mis-tagged as ORG)
    if bool(_ORG_FP_PHRASES.match(stripped)):
        return True

    # Sentence fragment check: if contains lowercase grammatical verbs.
    # If span ends with a legal suffix BUT starts with a lowercase word, it's still
    # a fragment — suppress it; CompanyNameRecognizer regex will catch the name alone.
    _LEGAL_SUFFIX_END = re.compile(
        r"\b(Private\s+Limited|Pvt\.?\s*Ltd\.?|Public\s+Limited|Limited|LLP|"
        r"Corporation|Corp\.?|Incorporated|Inc\.?|Holdings|Technologies|Solutions|"
        r"Services|Industries|Enterprises|Investments|Finance|Securities)\s*\.?$",
        re.IGNORECASE,
    )
    has_legal_suffix = bool(_LEGAL_SUFFIX_END.search(stripped))
    starts_lowercase = bool(re.match(r"^[a-z]", stripped))

    # Fragment starting with lowercase even if it ends with a legal suffix → suppress
    if starts_lowercase and has_legal_suffix:
        return True

    if not has_legal_suffix:
        words = [w.lower() for w in re.findall(r"\b[a-z]+\b", stripped)]
        if any(w in _FRAGMENT_VERBS for w in words):
            return True

    return False


# All-caps acronyms / regulatory codes that spaCy mis-tags as PERSON
_PERSON_FP_ACRONYMS: set = {
    "SCRR", "SEBI", "ICDR", "SCRA", "FEMA", "IFRS", "RBI", "NSE", "BSE",
    "MCA", "ROC", "CIN", "DIN", "PAN", "TAN", "GST", "IPO", "KMP", "WTD",
    "CMD", "CFO", "COO", "CSR", "AGM", "EGM", "MOA", "AOA", "NRI", "FPI",
    "QIB", "HNI", "SME", "MSME", "NBFC", "RERA", "PMLA", "IRDA", "PFRDA",
}

# Generic single words / Indian place-words that spaCy mis-tags as PERSON
_PERSON_FP_WORDS = {
    # Field labels
    "email", "telephone", "website", "contact", "phone", "fax", "mobile",
    # Generic business/document terms
    "fiscals", "fiscal", "annexure", "schedule", "appendix", "enclosure",
    "prospectus", "memorandum", "compliance", "indebtedness",
    # Indian geographic administrative terms that appear in addresses
    "taluka", "taluk", "tehsil", "district", "village", "gram", "nagar",
    "mauje", "ward", "sector", "block", "plot", "survey",
}

# Indian city / town names that spaCy commonly mis-tags as PERSON
_INDIAN_PLACES = {
    "mumbai", "pune", "delhi", "bangalore", "bengaluru", "chennai", "hyderabad",
    "kolkata", "ahmedabad", "surat", "jaipur", "lucknow", "kanpur", "nagpur",
    "baner", "khed", "chakan", "vikhroli", "bandra", "andheri", "kurla",
    "thane", "navi", "vasai", "nashik", "aurangabad", "solapur", "kolhapur",
    "ahmednagar", "ahilyanagar", "parner", "shirur", "birdewadi",
    "churchgate", "nariman", "worli", "dadar", "powai", "goregaon",
    "marol", "sakinaka", "jogeshwari", "malad", "kandivali", "borivali",
    "supa", "palve", "khurd",
}


def _is_person_fp(span: str) -> bool:
    """Return True if the PERSON span is a known false positive."""
    stripped = span.strip()
    lower = stripped.lower()

    # Single word checks
    if lower in _PERSON_FP_WORDS:
        return True

    # All place-name tokens (every word is an Indian place)
    tokens = [t.lower() for t in re.split(r"[\s\-]+", stripped) if t]
    if tokens and all(t in _INDIAN_PLACES for t in tokens):
        return True
    # Majority place-name: ≥2 tokens and all are place names (e.g. "Taluka Khed", "Supa Ahilyanagar")
    if len(tokens) >= 1 and all(t in _INDIAN_PLACES or t in _PERSON_FP_WORDS for t in tokens):
        return True

    # All-caps token(s) that are regulatory/acronym, not personal names
    if re.fullmatch(r"[A-Z]{2,8}(\s+[A-Z]{2,8})*", stripped):
        if stripped in _PERSON_FP_ACRONYMS:
            return True
        # Generic: if every word is ≤4 uppercase chars it's almost certainly an acronym
        if all(len(w) <= 4 for w in stripped.split()):
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
    """Return the best available spaCy model.
    Preference: SPACY_MODEL env var > en_core_web_sm (memory-safe for cloud containers) > md > lg.
    """
    import os
    import spacy
    env_model = os.environ.get("SPACY_MODEL")
    if env_model and spacy.util.is_package(env_model):
        logger.info("Using spaCy model from env: %s", env_model)
        return env_model

    preference = ["en_core_web_sm", "en_core_web_md", "en_core_web_lg"]
    for model in preference:
        if spacy.util.is_package(model):
            logger.info("Using spaCy model: %s", model)
            return model
    raise RuntimeError(
        "No compatible spaCy model found. Install one with:\n"
        "  python -m spacy download en_core_web_sm"
    )


# ---------------------------------------------------------------------------
# Engine construction
# ---------------------------------------------------------------------------

def build_analyzer(spacy_model: Optional[str] = None):
    """
    Build a Presidio AnalyzerEngine with:
      - spaCy NLP engine (best available model)
      - All Presidio built-in recognizers
      - All custom recognizers

    Returns (analyzer, raw_nlp) — the raw spaCy nlp object is exposed so
    callers can use nlp.pipe() for fast batch pre-processing.
    """
    import spacy
    model_name = spacy_model or _select_spacy_model()
    logger.info("Building AnalyzerEngine with model '%s'", model_name)

    nlp_config = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": model_name}],
    }
    provider = NlpEngineProvider(nlp_configuration=nlp_config)
    nlp_engine = provider.create_engine()

    # Grab the raw spaCy model so we can call nlp.pipe() for batch processing
    raw_nlp = nlp_engine.nlp.get("en") or spacy.load(model_name)

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

    return engine, raw_nlp


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
    """Run Presidio analyzer on a single text string; return raw results."""
    if not text or not text.strip():
        return []
    try:
        results = analyzer.analyze(
            text=text,
            language=language,
            entities=None,
            score_threshold=0.0,
        )
        return results
    except Exception as exc:
        logger.warning("Analyzer error on text snippet: %s", exc)
        return []


def batch_analyze_texts(
    analyzer: AnalyzerEngine,
    raw_nlp,
    texts: List[str],
    batch_size: int = 64,
    max_workers: int = 4,
    language: str = "en",
) -> List[List[RecognizerResult]]:
    """
    Fast batch PII analysis using two optimisations:

    1. **nlp.pipe()** — runs spaCy NER over all texts in a single vectorised
       pass (batch_size units at a time), amortising tokeniser + model overhead.

    2. **ThreadPoolExecutor** — the per-unit Presidio rule-based recognizers
       (regex, pattern matching) are CPU-light and GIL-friendly; running them
       concurrently across workers fills the time spaCy would otherwise spend
       idling between batches.

    Returns a list aligned 1-to-1 with `texts`.
    """
    from presidio_analyzer.nlp_engine import NlpArtifacts

    n = len(texts)
    if n == 0:
        return []

    logger.info("Batch NLP pass: %d units, batch_size=%d, workers=%d", n, batch_size, max_workers)
    t0 = time.perf_counter()

    # ── Step 1: single nlp.pipe() pass over all texts ──────────────────────
    # Disable heavy pipes not needed for NER (parser, lemmatizer) for speed.
    disable = [p for p in ("parser", "lemmatizer", "attribute_ruler") if p in raw_nlp.pipe_names]
    docs = list(raw_nlp.pipe(texts, batch_size=batch_size, disable=disable))

    t1 = time.perf_counter()
    logger.info("nlp.pipe() completed in %.1fs", t1 - t0)

    # ── Step 2: build NlpArtifacts from each doc ────────────────────────────
    # Get the nlp_engine reference from the analyzer so NlpArtifacts is happy
    nlp_engine_ref = analyzer.nlp_engine

    def make_artifacts(doc) -> NlpArtifacts:
        tokens_indices = [t.idx for t in doc]
        lemmas = [t.lemma_ for t in doc]
        scores = [1.0] * len(doc)
        return NlpArtifacts(
            entities=list(doc.ents),          # real spaCy Span objects
            tokens=doc,                         # real spaCy Doc (not a list)
            tokens_indices=tokens_indices,
            lemmas=lemmas,
            nlp_engine=nlp_engine_ref,
            language="en",
            scores=scores,
        )

    # ── Step 3: run Presidio recognizers concurrently (pattern + custom) ───
    results: List[Optional[List[RecognizerResult]]] = [None] * n

    _CUE_KEYWORDS = ("ltd", "limited", "llp", "pvt", "corp", "inc", "road", "nagar", "street", "floor", "office", "bank", "mumbai", "pune", "delhi", "director", "officer", "person", "contact")

    def _analyze_one(idx: int, text: str, doc):
        stripped = text.strip()
        if not stripped or len(stripped) < 3:
            return idx, []

        has_ents = len(doc.ents) > 0
        text_lower = text.lower()
        has_cues = (
            any(c in text for c in "@0123456789")
            or any(kw in text_lower for kw in _CUE_KEYWORDS)
        )

        if not has_ents and not has_cues:
            return idx, []

        artifacts = make_artifacts(doc)
        try:
            res = analyzer.analyze(
                text=text,
                language=language,
                entities=None,
                score_threshold=0.0,
                nlp_artifacts=artifacts,
            )
            return idx, res
        except Exception as exc:
            logger.warning("Analyzer error at index %d: %s", idx, exc)
            return idx, []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(_analyze_one, i, texts[i], docs[i])
            for i in range(n)
        ]
        for fut in as_completed(futures):
            idx, res = fut.result()
            results[idx] = res

    t2 = time.perf_counter()
    logger.info("Presidio recognition pass completed in %.1fs (total: %.1fs)", t2 - t1, t2 - t0)

    return results  # type: ignore


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
                logger.debug("Suppressed ORG FP '%s' [%d-%d]", span, r.start, r.end)
                continue

        # Suppress PERSON false positives (acronyms mis-tagged by spaCy NER)
        if r.entity_type == "PERSON" and text:
            span = text[r.start:r.end]
            if _is_person_fp(span):
                logger.debug("Suppressed PERSON FP '%s' [%d-%d]", span, r.start, r.end)
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
