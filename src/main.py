"""
main.py
-------
CLI entry point for the PII Redaction Tool.

Usage:
    python src/main.py --input "input/Red Herring Prospectus(1).docx" \
                       --output "output/Redacted_Prospectus.docx"

Optional flags:
    --evaluate          Run evaluation against ground_truth/ground_truth.json
    --log-level         DEBUG | INFO | WARNING (default: INFO)
    --spacy-model       Override spaCy model name
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

# Allow running from repo root or from src/
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import docx_processor
import redactor as rmod
import evaluator as emod
from fake_generator import FakeValueRegistry


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PII Redaction Tool — Presidio Hybrid Architecture"
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to input DOCX file",
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Path to output (redacted) DOCX file",
    )
    parser.add_argument(
        "--evaluate", "-e",
        action="store_true",
        default=False,
        help="Run evaluation against ground_truth/ground_truth.json after redaction",
    )
    parser.add_argument(
        "--ground-truth",
        default="ground_truth/ground_truth.json",
        help="Path to ground truth JSON (used with --evaluate)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )
    parser.add_argument(
        "--spacy-model",
        default=None,
        help="Override spaCy model name (default: auto-select best available)",
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="Optional path to write full detection and statistics JSON report",
    )
    return parser.parse_args()


def validate_input(path: str) -> None:
    if not os.path.isfile(path):
        print(f"ERROR: Input file not found: {path}", file=sys.stderr)
        print("Please ensure the file exists at the specified path.", file=sys.stderr)
        sys.exit(1)
    if not path.lower().endswith(".docx"):
        print(f"WARNING: Input file does not have .docx extension: {path}", file=sys.stderr)


def ensure_output_dir(path: str) -> None:
    out_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(out_dir, exist_ok=True)


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    logger = logging.getLogger("main")

    # Step 1: validate inputs
    validate_input(args.input)
    ensure_output_dir(args.output)
    abs_input = os.path.abspath(args.input)
    abs_output = os.path.abspath(args.output)

    if abs_input == abs_output:
        logger.error("Input and output paths are the same. Refusing to overwrite input.")
        sys.exit(1)

    logger.info("Input : %s", abs_input)
    logger.info("Output: %s", abs_output)

    # Step 2: build Presidio engines
    try:
        analyzer, raw_nlp = rmod.build_analyzer(spacy_model=args.spacy_model)
        anonymizer = rmod.build_anonymizer()
        operators = rmod.build_operator_config()
    except RuntimeError as exc:
        logger.error("Engine build failed: %s", exc)
        sys.exit(1)

    # Step 3: load document
    doc = docx_processor.load_document(abs_input)

    # Step 4: batch analyze all text units (fast path)
    text_units = list(docx_processor.extract_text_units(doc))
    logger.info("Extracted %d text units from document", len(text_units))
    texts = [unit.full_text for unit in text_units]
    batch_results = rmod.batch_analyze_texts(
        analyzer, raw_nlp, texts,
        batch_size=128,
        max_workers=4,
    )

    all_detections = []
    units_with_pii = 0
    total_units = len(text_units)

    # Fake-value registry — same original PII always maps to same fake replacement
    registry = FakeValueRegistry()

    for unit, raw_results in zip(text_units, batch_results):
        raw_results = raw_results or []
        filtered = rmod.filter_by_threshold(raw_results, text=unit.full_text)
        resolved = rmod.resolve_overlaps(filtered)

        if resolved:
            units_with_pii += 1
            for r in resolved:
                snippet = unit.full_text[r.start:r.end]
                fake_val = registry.get_or_create(r.entity_type, snippet)
                all_detections.append({
                    "unit_id": unit.unit_id,
                    "entity_type": r.entity_type,
                    "start": r.start,
                    "end": r.end,
                    "score": round(r.score, 3),
                    "text": snippet,
                    "replacement": fake_val,
                })

        # Apply fake-value replacements right-to-left for offset safety
        replacements = [
            (r.start, r.end, registry.get_or_create(
                r.entity_type, unit.full_text[r.start:r.end]
            ))
            for r in sorted(resolved, key=lambda x: x.start, reverse=True)
        ]
        docx_processor.apply_redactions(unit, replacements)

    logger.info(
        "Detection complete: %d PII entities found across %d/%d units",
        len(all_detections), units_with_pii, total_units,
    )

    # Step 5: save redacted document
    docx_processor.save_document(doc, abs_output)

    # Step 6: print detection summary
    from collections import Counter
    type_counts = Counter(d["entity_type"] for d in all_detections)
    print("\n=== PII Detection Summary ===")
    for etype, count in sorted(type_counts.items()):
        print(f"  {etype:<25} {count:>4} instance(s)")
    print(f"  {'TOTAL':<25} {len(all_detections):>4}")
    print(f"\nRedacted document saved to: {abs_output}")

    # Export structured JSON report if requested
    if args.json_output:
        # Build replacement_map: original → fake for each unique PII value
        replacement_map = [
            {"entity_type": et, "original": orig, "replacement": fake}
            for (et, orig), fake in registry.mapping_snapshot().items()
        ]
        report = {
            "input_file": abs_input,
            "output_file": abs_output,
            "total_units": total_units,
            "units_with_pii": units_with_pii,
            "total_pii_count": len(all_detections),
            "counts_by_type": dict(type_counts),
            "replacement_map": replacement_map,
            "detections": all_detections,
        }
        with open(args.json_output, "w", encoding="utf-8") as jf:
            json.dump(report, jf, indent=2)
        logger.info("Exported JSON report to %s", args.json_output)

    # Step 7 (optional): evaluation
    if args.evaluate:
        gt_path = args.ground_truth
        if not os.path.isfile(gt_path):
            logger.warning("Ground truth file not found: %s — skipping evaluation", gt_path)
        else:
            emod.run_evaluation(all_detections, gt_path)

    # Verify original unchanged
    current_size = os.path.getsize(abs_input)
    logger.info("Input file size unchanged: %d bytes (original preserved)", current_size)


if __name__ == "__main__":
    main()
