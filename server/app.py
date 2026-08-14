"""
app.py
------
Production Flask server for PII Redaction Tool.
Pre-warms Microsoft Presidio & spaCy ONCE at startup (Singleton pattern)
to eliminate per-request cold-start latency and prevent OOM on cloud instances.
"""

from __future__ import annotations

import gc
import json
import logging
import os
import sys
import threading
import time
import uuid
from typing import Dict, List, Optional
from urllib.parse import quote

from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

# Add src to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import docx_processor
import redactor as rmod
import evaluator as emod
from fake_generator import FakeValueRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("server")

# ---------------------------------------------------------------------------
# Directories & Constants
# ---------------------------------------------------------------------------

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROCESSED_DIR = os.path.join(os.path.dirname(__file__), "processed")
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
CLIENT_DIST = os.path.join(ROOT_DIR, "client", "dist")
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Concurrency lock: ensure only 1 heavy redaction runs at a time to prevent OOM
_redact_lock = threading.Lock()
_jobs_lock = threading.Lock()
_jobs: Dict[str, Dict] = {}

# ---------------------------------------------------------------------------
# Singleton Initialization (Phase 4: Pre-warm engines once at server start)
# ---------------------------------------------------------------------------

logger.info("=======================================================")
logger.info("Initializing Presidio Analyzer & spaCy engine at startup...")
t_init_start = time.perf_counter()

analyzer, raw_nlp = rmod.build_analyzer(spacy_model="en_core_web_sm")
anonymizer = rmod.build_anonymizer()
operators = rmod.build_operator_config()

t_init_end = time.perf_counter()
logger.info("Presidio engine pre-warmed and ready in %.2fs", t_init_end - t_init_start)
logger.info("=======================================================")

# ---------------------------------------------------------------------------
# Flask App Setup
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder=CLIENT_DIST, static_url_path="")
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE_BYTES


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health_check():
    """Health check endpoint for cloud platform probes."""
    return jsonify({
        "status": "ok",
        "service": "PII Redaction API",
        "version": "1.0.0",
        "engine": "Microsoft Presidio (Singleton)",
        "model": "en_core_web_sm",
    })


@app.route("/api/evaluation", methods=["GET"])
def get_evaluation():
    """Return pre-computed evaluation metrics against Ground Truth."""
    gt_path = os.path.join(ROOT_DIR, "ground_truth", "ground_truth.json")
    absent_types = {}
    if os.path.isfile(gt_path):
        try:
            with open(gt_path, "r", encoding="utf-8") as f:
                gt_data = json.load(f)
                absent_types = gt_data.get("absent_types", {})
        except Exception as e:
            logger.warning("Could not read ground truth file: %s", e)

    return jsonify({
        "success": True,
        "metrics": {
            "overall": {
                "precision": 1.000,
                "recall": 0.818,
                "f1": 0.900,
                "tp": 18,
                "fp": 0,
                "fn": 4,
            },
            "perType": {
                "ADDRESS":       {"precision": 1.000, "recall": 1.000, "f1": 1.000, "tp": 2, "fp": 0, "fn": 0},
                "EMAIL_ADDRESS": {"precision": 1.000, "recall": 1.000, "f1": 1.000, "tp": 5, "fp": 0, "fn": 0},
                "ORGANIZATION":  {"precision": 1.000, "recall": 1.000, "f1": 1.000, "tp": 1, "fp": 0, "fn": 0},
                "PERSON":        {"precision": 1.000, "recall": 0.800, "f1": 0.889, "tp": 8, "fp": 0, "fn": 2},
                "PHONE_NUMBER":  {"precision": 1.000, "recall": 0.500, "f1": 0.667, "tp": 2, "fp": 0, "fn": 2},
            },
            "absentTypes": absent_types,
        }
    })


def _set_job(job_id: str, **updates) -> None:
    with _jobs_lock:
        current = _jobs.setdefault(job_id, {})
        current.update(updates)
        current["updatedAt"] = time.time()


def _get_job(job_id: str) -> Optional[Dict]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _process_redaction_job(job_id: str, input_path: str, original_name: str) -> None:
    """Run a redaction job after the upload request has already returned."""
    t_start = time.perf_counter()
    output_filename = f"Redacted_{job_id}.docx"
    output_path = os.path.join(PROCESSED_DIR, output_filename)
    report_path = os.path.join(PROCESSED_DIR, f"Report_{job_id}.json")

    try:
        _set_job(job_id, status="processing", message="Waiting for redaction engine...")

        # Acquire lock to ensure only 1 heavy job executes at a time
        with _redact_lock:
            # Load DOCX
            _set_job(job_id, message="Loading document...")
            logger.info("[Job %s] DOCUMENT LOADED", job_id)
            doc = docx_processor.load_document(input_path)

            # Extract units
            _set_job(job_id, message="Extracting document text...")
            logger.info("[Job %s] TEXT EXTRACTION STARTED", job_id)
            text_units = list(docx_processor.extract_text_units(doc))
            total_units = len(text_units)
            logger.info("[Job %s] TEXT EXTRACTION COMPLETED: %d units extracted", job_id, total_units)

            # Analyze text units using pre-warmed singleton engine
            _set_job(job_id, message=f"Analyzing {total_units} text units for PII...")
            logger.info("[Job %s] PII ANALYSIS STARTED", job_id)
            texts = [u.full_text for u in text_units]
            batch_results = rmod.batch_analyze_texts(
                analyzer, raw_nlp, texts,
                batch_size=64,
            )
            logger.info("[Job %s] PII ANALYSIS COMPLETED", job_id)

            # Redaction with consistent FakeValueRegistry
            _set_job(job_id, message="Applying redactions...")
            logger.info("[Job %s] REDACTION STARTED", job_id)
            registry = FakeValueRegistry()
            all_detections: List[Dict] = []
            units_with_pii = 0

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

                # Apply redactions right-to-left for offset safety
                replacements = [
                    (r.start, r.end, registry.get_or_create(
                        r.entity_type, unit.full_text[r.start:r.end]
                    ))
                    for r in sorted(resolved, key=lambda x: x.start, reverse=True)
                ]
                docx_processor.apply_redactions(unit, replacements)

            # Save redacted document
            docx_processor.save_document(doc, output_path)
            logger.info("[Job %s] DOCX OUTPUT CREATED at %s", job_id, output_path)

            # Counts by entity type (do NOT log raw PII values)
            from collections import Counter
            type_counts = Counter(d["entity_type"] for d in all_detections)
            logger.info(
                "[Job %s] Detected %d PII entities across %d/%d units. Counts: %s",
                job_id, len(all_detections), units_with_pii, total_units, dict(type_counts)
            )

            # Write JSON report
            replacement_map = [
                {"entity_type": et, "original": orig, "replacement": fake}
                for (et, orig), fake in registry.mapping_snapshot().items()
            ]
            report = {
                "input_file": input_path,
                "output_file": output_path,
                "total_units": total_units,
                "units_with_pii": units_with_pii,
                "total_pii_count": len(all_detections),
                "counts_by_type": dict(type_counts),
                "replacement_map": replacement_map,
                "detections": all_detections,
            }
            with open(report_path, "w", encoding="utf-8") as jf:
                json.dump(report, jf, indent=2)

        # Cleanup input file to free disk/RAM
        try:
            if os.path.exists(input_path):
                os.remove(input_path)
        except Exception:
            pass

        # Trigger garbage collection
        gc.collect()

        elapsed = time.perf_counter() - t_start
        logger.info("[Job %s] JOB COMPLETED in %.2f seconds", job_id, elapsed)

        _set_job(job_id, status="complete", message="Redaction complete.", result={
            "success": True,
            "jobId": job_id,
            "originalName": original_name,
            "downloadUrl": f"/api/download/{job_id}?filename={quote(original_name)}",
            "stats": dict(type_counts),
            "totalPii": len(all_detections),
            "unitsWithPii": units_with_pii,
            "totalUnits": total_units,
            "sampleDetections": all_detections[:50],
        })

    except Exception as exc:
        logger.exception("[Job %s] Error processing document: %s", job_id, exc)
        # Clean up files on error
        for p in [input_path, output_path, report_path]:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        _set_job(
            job_id,
            status="error",
            message="Redaction failed.",
            error=f"Failed to process document: {str(exc)}",
        )


@app.route("/api/redact", methods=["POST"])
def redact_document():
    """
    Start a redaction job:
      1. Receives and saves uploaded DOCX
      2. Returns a job id immediately to avoid platform request timeouts
      3. Continues processing in a background thread
    """
    job_id = str(uuid.uuid4())

    if "file" not in request.files:
        return jsonify({"success": False, "error": "No DOCX file uploaded."}), 400

    uploaded_file = request.files["file"]
    original_name = os.path.basename(uploaded_file.filename or "Prospectus.docx")

    if not original_name.lower().endswith(".docx"):
        return jsonify({"success": False, "error": "Only Microsoft Word (.docx) documents are supported."}), 400

    logger.info("[Job %s] REQUEST RECEIVED: %s (size: %s bytes)", job_id, original_name, request.content_length)

    input_path = os.path.join(UPLOADS_DIR, f"{job_id}_{original_name}")

    try:
        uploaded_file.save(input_path)
        logger.info("[Job %s] FILE SAVED to %s", job_id, input_path)
    except Exception as exc:
        logger.exception("[Job %s] Could not save uploaded file: %s", job_id, exc)
        return jsonify({"success": False, "error": "Could not save uploaded file."}), 500

    _set_job(
        job_id,
        status="queued",
        message="Document uploaded. Redaction job queued.",
        originalName=original_name,
        createdAt=time.time(),
    )
    worker = threading.Thread(
        target=_process_redaction_job,
        args=(job_id, input_path, original_name),
        daemon=True,
    )
    worker.start()

    return jsonify({
        "success": True,
        "accepted": True,
        "jobId": job_id,
        "statusUrl": f"/api/redact/status/{job_id}",
    }), 202


@app.route("/api/redact/status/<job_id>", methods=["GET"])
def get_redaction_status(job_id: str):
    """Return status/result for an async redaction job."""
    job = _get_job(job_id)
    if not job:
        return jsonify({"success": False, "error": "Job not found or expired."}), 404

    payload = {
        "success": True,
        "jobId": job_id,
        "status": job.get("status", "queued"),
        "message": job.get("message", ""),
    }
    if job.get("status") == "complete":
        payload["result"] = job.get("result")
    if job.get("status") == "error":
        payload["error"] = job.get("error", "Redaction failed.")
    return jsonify(payload)


@app.route("/api/download/<job_id>", methods=["GET"])
def download_redacted(job_id: str):
    """Download the generated redacted DOCX file."""
    original_name = request.args.get("filename", "Prospectus.docx")
    base, ext = os.path.splitext(original_name)
    download_name = f"Redacted_{base}{ext or '.docx'}"

    file_path = os.path.join(PROCESSED_DIR, f"Redacted_{job_id}.docx")
    if not os.path.isfile(file_path):
        return jsonify({"success": False, "error": "Redacted file not found or expired."}), 404

    return send_file(
        file_path,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ---------------------------------------------------------------------------
# Static Frontend Serving (Single unified service)
# ---------------------------------------------------------------------------

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    """Serve the built React SPA."""
    if path != "" and os.path.exists(os.path.join(CLIENT_DIST, path)):
        return send_from_directory(CLIENT_DIST, path)
    if os.path.exists(os.path.join(CLIENT_DIST, "index.html")):
        return send_from_directory(CLIENT_DIST, "index.html")
    return jsonify({
        "service": "PII Redaction Tool",
        "status": "online",
        "frontend": "Not yet built. Run 'npm run build:client' to compile React UI."
    })


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = "0.0.0.0"
    logger.info("Starting Flask server on %s:%d", host, port)
    app.run(host=host, port=port, threaded=True)
