"""
evaluator.py
------------
Evaluation module: loads independently curated ground_truth.json and computes
TP / FP / FN → Precision / Recall / F1 per entity type and overall.

Ground truth format (one entry):
{
    "unit_id": "body-para-142",
    "entity_type": "EMAIL_ADDRESS",
    "start": 42,
    "end": 61,
    "text": "contact@example.com"
}

Matching rule:
    A detector result matches a ground-truth entry if:
      - entity_type matches exactly, AND
      - same unit_id, AND
      - overlap is >= MIN_OVERLAP_RATIO of the ground-truth span length
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

MIN_OVERLAP_RATIO = 0.50  # 50% overlap required to count as a match


def load_ground_truth(path: str) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        entries = data.get("entries", [])
        absent = data.get("absent_types", {})
    else:
        entries = data
        absent = {}
    logger.info("Loaded %d ground truth entries from %s", len(entries), path)
    return entries, absent


def _spans_overlap_enough(
    det_start: int, det_end: int,
    gt_start: int, gt_end: int,
) -> bool:
    overlap_start = max(det_start, gt_start)
    overlap_end = min(det_end, gt_end)
    if overlap_end <= overlap_start:
        return False
    overlap_len = overlap_end - overlap_start
    gt_len = gt_end - gt_start
    return (overlap_len / gt_len) >= MIN_OVERLAP_RATIO if gt_len > 0 else False


def run_evaluation(
    detections: List[Dict[str, Any]],
    gt_path: str,
) -> None:
    """
    Compare detections against ground truth and print metrics table.

    detections: list of dicts with keys unit_id, entity_type, start, end
    """
    ground_truth, absent_types = load_ground_truth(gt_path)

    # Index ground truth by (unit_id, entity_type)
    gt_by_unit: Dict[str, List[Dict]] = defaultdict(list)
    for entry in ground_truth:
        gt_by_unit[entry["unit_id"]].append(entry)

    # Track per-type metrics
    entity_types = set(d["entity_type"] for d in detections) | set(
        e["entity_type"] for e in ground_truth
    )

    per_type: Dict[str, Dict[str, int]] = {
        et: {"TP": 0, "FP": 0, "FN": 0} for et in entity_types
    }

    # Match detections to ground truth
    matched_gt_ids = set()  # indices of GT entries already matched

    for det in detections:
        unit_id = det["unit_id"]
        etype = det["entity_type"]
        d_start = det["start"]
        d_end = det["end"]

        # Find matching GT entry
        found_match = False
        for gt_idx, gt_entry in enumerate(ground_truth):
            if gt_idx in matched_gt_ids:
                continue
            if gt_entry["unit_id"] != unit_id:
                continue
            if gt_entry["entity_type"] != etype:
                continue
            if _spans_overlap_enough(d_start, d_end, gt_entry["start"], gt_entry["end"]):
                per_type[etype]["TP"] += 1
                matched_gt_ids.add(gt_idx)
                found_match = True
                break

        if not found_match:
            # Only count as FP if the unit_id is part of our ground truth evaluation set
            if unit_id in gt_by_unit:
                per_type[etype]["FP"] += 1

    # Remaining unmatched GT entries are FNs
    for gt_idx, gt_entry in enumerate(ground_truth):
        if gt_idx not in matched_gt_ids:
            etype = gt_entry["entity_type"]
            if etype not in per_type:
                per_type[etype] = {"TP": 0, "FP": 0, "FN": 0}
            per_type[etype]["FN"] += 1

    # Calculate and print metrics
    print("\n" + "=" * 70)
    print("  PII Redaction Evaluation Report")
    print("=" * 70)
    print(
        f"  {'Entity Type':<25} {'TP':>4} {'FP':>4} {'FN':>4} "
        f"{'Prec':>7} {'Rec':>7} {'F1':>7}"
    )
    print("-" * 70)

    total_tp = total_fp = total_fn = 0

    for etype in sorted(per_type.keys()):
        m = per_type[etype]
        tp, fp, fn = m["TP"], m["FP"], m["FN"]
        total_tp += tp
        total_fp += fp
        total_fn += fn

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1   = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0

        # Note if absent from GT
        gt_count = sum(1 for e in ground_truth if e["entity_type"] == etype)
        if gt_count == 0:
            note = "  [not in GT sample]"
        else:
            note = ""

        print(
            f"  {etype:<25} {tp:>4} {fp:>4} {fn:>4} "
            f"{prec:>7.3f} {rec:>7.3f} {f1:>7.3f}{note}"
        )

    print("-" * 70)
    o_prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    o_rec  = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    o_f1   = (2 * o_prec * o_rec / (o_prec + o_rec)) if (o_prec + o_rec) > 0 else 0.0
    print(
        f"  {'OVERALL (GT sample)':<25} {total_tp:>4} {total_fp:>4} {total_fn:>4} "
        f"{o_prec:>7.3f} {o_rec:>7.3f} {o_f1:>7.3f}"
    )
    print("=" * 70)

    if absent_types:
        print("\n--- Entities Absent from Evaluation Data ---")
        for etype, reason in sorted(absent_types.items()):
            print(f"  {etype:<20}: {reason}")
        print("=" * 70)
    print(
        "\nNote: Accuracy (token-level) is not reported because the document is\n"
        "highly imbalanced (>99% non-PII tokens). Span-level Precision/Recall/F1\n"
        "are the correct primary metrics for this task.\n"
    )
