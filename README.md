# PII Redaction Tool — Microsoft Presidio Hybrid Architecture with React & Node.js

A production-quality full-stack solution for detecting and redacting Personally Identifiable Information (PII) in Microsoft Word (`.docx`) documents using Microsoft Presidio, spaCy NLP, Node.js Express API, and a modern React.js dashboard.

---

## 1. Features & Architecture

```
User Browser (React.js UI Dashboard)
                 │
                 ▼  (Upload .docx / Download sanitized file)
Node.js Express Server (server/index.js)
                 │
                 ▼  (child_process execution with JSON IPC)
Python Core Engine (src/main.py)
  ├─► docx_processor.py      (Run-level offset mapper: preserves bold, italic, tables & headers)
  ├─► recognizers.py         (Custom Presidio recognizers for Indian Phones, SSN, DOB, Company, Address)
  ├─► redactor.py            (Hybrid Presidio Analyzer & Anonymizer with priority-aware overlap resolution)
  └─► evaluator.py           (Independently curated ground truth evaluation & metrics)
```

- **Full Format Preservation**: Treats paragraphs and table cells as logical text units, executes NLP on full text, and maps character offsets back to individual runs without converting to plain text.
- **Strict False-Positive Protection**: Financial amounts (e.g. `₹5,000 million`), page numbers, years (`FY 2024-25`), regulation numbers, and generic business references (`the Company`, `our Bank`) are never redacted.
- **Modern Full-Stack UI**: Single-click drag-and-drop file upload, live progress animation, PII breakdown analytics dashboard, and instant `.docx` download.
- **Cloud-Ready**: Includes `Dockerfile` and `render.yaml` for 1-click deployment on Render, Railway, or Hugging Face Spaces.

---

## 2. PII Types Supported

| Entity Type | Redaction Label | Detection Strategy | Confidence Threshold |
|---|---|---|---|
| **Full Names** | `[REDACTED: PERSON_NAME]` | Presidio / spaCy `en_core_web_lg` NER + Context (`Director:`, `Promoter:`, `Mr.`, `Ms.`) | 0.70 |
| **Email Addresses** | `[REDACTED: EMAIL]` | Regex + Presidio built-in `EMAIL_ADDRESS` | 0.50 |
| **Phone Numbers** | `[REDACTED: PHONE]` | Custom `IndianPhoneRecognizer` (`+91 XX XXXX XXXX`, `0XX 4509 4400`) + Presidio `PHONE_NUMBER` | 0.60 |
| **Company Names** | `[REDACTED: COMPANY_NAME]` | 3-layer gate: spaCy `ORG` NER + Suffix patterns (`Pvt. Ltd.`, `LLP`, `Limited`) + Generic FP suppression | 0.75 |
| **Physical Addresses** | `[REDACTED: ADDRESS]` | Multi-signal: PIN code anchor (`\b[1-9][0-9]{5}\b`) + Address keywords (`Plot`, `Road`, `Taluka`) + Multi-line expansion | 0.65 |
| **SSNs** | `[REDACTED: SSN]` | Custom `SSNStrictRecognizer` (`\d{3}-\d{2}-\d{4}` with hyphens + context) | 0.85 |
| **Credit Card Numbers** | `[REDACTED: CREDIT_CARD]` | Presidio `CREDIT_CARD` with Luhn checksum validation | 0.80 |
| **Dates of Birth** | `[REDACTED: DOB]` | Custom `DOBRecognizer` (context-gated: requires `DOB:`, `Date of Birth:`, `Born:` within 60 chars) | 0.90 |
| **IP Addresses** | `[REDACTED: IP_ADDRESS]` | Presidio `IP_ADDRESS` with IPv4 octet validation | 0.60 |

---

## 3. Evaluation Report

Evaluated against an independently curated ground truth dataset (`ground_truth/ground_truth.json`):

```
======================================================================
  PII Redaction Evaluation Report
======================================================================
  Entity Type                 TP   FP   FN    Prec     Rec      F1
----------------------------------------------------------------------
  ADDRESS                      2    0    0   1.000   1.000   1.000
  EMAIL_ADDRESS                5    0    0   1.000   1.000   1.000
  ORGANIZATION                 1    8    0   0.111   1.000   0.200
  PERSON                       7    0    3   1.000   0.700   0.824
  PHONE_NUMBER                 4    0    0   1.000   1.000   1.000
----------------------------------------------------------------------
  OVERALL (GT sample)         19    8    3   0.704   0.864   0.776
======================================================================

--- Entities Absent from Evaluation Data ---
  CREDIT_CARD         : Not present in this document (financial figures are present, but no payment credit card numbers)
  DATE_OF_BIRTH       : Not present in evaluated sample (governance section lists director bios without explicit DOB labels)
  IP_ADDRESS          : Not present in this document (legal financial prospectus without server network data)
  US_SSN              : Not present in this document (Indian prospectus; no US SSN format data)
======================================================================
```

> **Accuracy Note**: Token-level accuracy is not reported because the document is highly imbalanced (>99% non-PII tokens). Span-level Precision, Recall, and F1 are the primary metrics for this task.

---

## 4. Quick Start & Running Locally

### 1. Install Prerequisites
- Python 3.9+
- Node.js 18+

### 2. Install Dependencies
```bash
# Python dependencies
pip install -r requirements.txt
python -m spacy download en_core_web_lg

# Node.js server & client dependencies
npm run install:server
npm run install:client
```

### 3. Run the Web Application
```bash
# Production mode (Express serves built React frontend on port 5000):
npm run build:client
npm start

# Development mode (Vite on port 3000 + Express API on port 5000):
npm run dev
```
Open [http://localhost:5000](http://localhost:5000) (or [http://localhost:3000](http://localhost:3000) in dev mode).

### 4. CLI Usage (Python directly)
```bash
# Redact document
python src/main.py --input "input/Red Herring Prospectus(1).docx" --output "output/Redacted_Prospectus.docx"

# Redact with evaluation report
python src/main.py --input "input/Red Herring Prospectus(1).docx" --output "output/Redacted_Prospectus.docx" --evaluate

# Run automated test suite
pytest tests/test_pii.py -v
```

---

## 5. Cloud Deployment (Render / Railway / Docker)

### Option A: Render.com (1-Click Deployment)
1. Push this repository to GitHub.
2. In Render Dashboard, click **New > Web Service**.
3. Connect your repository. Render will automatically detect `render.yaml` and `Dockerfile`.
4. Click **Deploy**.

### Option B: Docker
```bash
docker build -t pii-redaction-tool .
docker run -p 5000:5000 pii-redaction-tool
```

---

## 6. Repository Directory Structure

```
.
├── src/                          # Python Core Engine
│   ├── main.py                   # CLI + JSON report output
│   ├── recognizers.py            # Presidio custom recognizers
│   ├── docx_processor.py         # Run-level offset mapper & writeback
│   ├── redactor.py               # Presidio pipeline & overlap resolution
│   └── evaluator.py              # Evaluation metrics calculator
├── tests/
│   └── test_pii.py               # Pytest suite (48 tests)
├── ground_truth/
│   └── ground_truth.json         # Verified ground truth dataset
├── server/                       # Node.js Express API Server
│   ├── index.js                  # Express API endpoints
│   └── package.json
├── client/                       # React.js Frontend (Vite)
│   ├── src/                      # Components, dashboard & styles
│   └── package.json
├── Dockerfile                    # Multi-stage Dockerfile
├── render.yaml                   # Render deployment blueprint
├── requirements.txt              # Python dependencies
└── package.json                  # Root runner scripts
```
