# SAT-SA: Supervisory Analytics Tool for SOC Assessment

SAT-SA is an offline, decision-support supervisory analytics platform designed for human examiners assessing Cyber Security Operations Center (SOC) operational effectiveness across Supervised Entities (CSEs).

> **Important**: SAT-SA is an offline analytical workbench. It does not perform real-time monitoring, does not replace a SIEM/SOC, and does not issue autonomous regulatory verdicts. Algorithmic outputs are explainable supervisory hypotheses with uncertainty bounds and alternative explanations; human examiners retain exclusive deliberation and decision authority.

---

## Architecture & Operational Trust Model

1. **Strict Immutability of Machine Findings**: Algorithmic rules and NLP models generate supervisory findings. Once persisted, findings are never updated, overwritten, or deleted by human decisions.
2. **Dedicated Append-Only Audit Lineage**: Human supervisory decisions are stored in dedicated audit tables with optimistic concurrency tracking (`version`, `superseded_decision_id`).
3. **Submodular Knapsack Portfolio Optimizer**: Budget-constrained examiner review portfolio selection balancing targeted high-risk findings, benign controls, and exploratory samples to maximize marginal hypothesis coverage ($\Delta H$).
4. **Frozen Point-in-Time Assessment Snapshots**: Exports snapshot database state up to an exact UTC cutoff timestamp, packaging standalone printable HTML, raw JSON, and cryptographic SHA-256 checksum manifests.
5. **Offline & Air-Gapped Runtime**: Once dependencies and model weights are initially provisioned, runtime operates with loopback-only binding (`127.0.0.1`), zero remote telemetry, zero external CDNs, and pre-bundled local assets.
6. **Initial Setup vs. Air-Gapped Operation Notice**: A source-only clone from GitHub requires initial internet access to fetch Python and Node dependencies and to provision the pinned model weights. For strictly air-gapped environments, use the self-contained offline release bundle generated via `scripts/build_offline_bundle.py`.

---

## Prerequisites

- **Python**: 3.12 or newer
- **uv**: Fast Python package installer and resolver (`pip install uv` or via standalone installer)
- **Node.js**: Node 18.x or 20.x LTS with `npm`
- **Git**: For source version control

---

## Quickstart Installation

### 1. Clone & Set Up Python Environment

Using `uv` (recommended):
```bash
# Sync all backend packages and developer dependencies
uv sync --all-extras
```

Alternatively using standard Python venv and pip:
```bash
python -m venv .venv
# On Linux/macOS:
source .venv/bin/activate
# On Windows PowerShell:
.venv\Scripts\Activate.ps1

pip install -e ".[dev]"
```

### 2. Set Up Web Frontend

```bash
# Install frontend dependencies
npm --prefix apps/web install
```

### 3. Configure Local Environment

Copy the example environment configuration:
```bash
# Linux / macOS:
cp .env.example .env

# Windows PowerShell:
Copy-Item .env.example .env
```

Configuration variables in `.env`:
- `ENVIRONMENT`: `development` or `production`
- `HOST`: Loopback host (`127.0.0.1`)
- `PORT`: API server port (`8000`)
- `DATABASE_URL`: SQLite connection URI (`sqlite:///storage/sat_sa.db` or `sqlite:///storage/sat_sa_demo.db`)
- `STORAGE_DIR`: Local uploaded evidence storage (`storage/raw_files`)
- `SESSION_SECRET`: Session authentication signing key

---

## Model Provisioning (Optional / Recommended)

SAT-SA uses a pinned Sentence-Transformers model (`sentence-transformers/all-MiniLM-L6-v2` at commit `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`) for offline semantic similarity analysis of investigation notes.

To keep the git repository lean and under GitHub upload size limits, model weights (`model.safetensors`, ~86.7 MB) are intentionally excluded from git tracking.

To download and cryptographically verify the model weights:
```bash
uv run python scripts/provision_model.py
```
This downloads allowlisted artifacts directly into `models/all-MiniLM-L6-v2/` and verifies them against `models/manifest.json`.

> **Note**: If the model is not provisioned, SAT-SA automatically falls back to deterministic lexical similarity matching, allowing the core application, rules engine, and supervisory analytics to operate without downloaded model weights.

---

## Database & Demo Initialization

### 1. Initialize Clean Database Schema
```bash
uv run alembic upgrade head
```

### 2. (Recommended) Seed Synthetic Demonstration Data
To safely experience the full prototype with multi-entity evaluation data, run the synthetic demonstration seeder targeting the dedicated demo database:

**Windows PowerShell:**
```powershell
$env:DATABASE_URL = "sqlite:///storage/sat_sa_demo.db"
uv run python scripts/initialize_demo_data.py --reset --tamper-demo
```

**Linux / macOS Bash:**
```bash
export DATABASE_URL="sqlite:///storage/sat_sa_demo.db"
uv run python scripts/initialize_demo_data.py --reset --tamper-demo
```

This populates:
- 4 banking CSE entities (`CSE-BANK-01` to `CSE-BANK-04`)
- 1 healthcare control entity (`CSE-HEALTH-01`)
- 3 historical quarters (`2026-Q1` through `2026-Q3`)
- Budgeted portfolio review items, human decisions, and audit trail
- Signed Merkle checkpoints and Fabric milestone receipt
- Validates cryptographic tamper detection on a disposable copy

### 3. Bootstrap Local Examiner / Admin Users
Create an administrative examiner user:
```bash
uv run python -m apps.api.cli create-admin --username admin --password "ExaminerPass123!" --entity-scope "*"
```

---

## Running the Application

### 1. Start Backend API Server
**Windows PowerShell:**
```powershell
$env:DATABASE_URL = "sqlite:///storage/sat_sa_demo.db"
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

**Linux / macOS Bash:**
```bash
export DATABASE_URL="sqlite:///storage/sat_sa_demo.db"
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

API documentation is accessible locally at `http://127.0.0.1:8000/docs`.

### 2. Start Frontend Web Interface
In a separate terminal:
```bash
npm --prefix apps/web run dev
```

Open your browser at `http://127.0.0.1:5173`.

### Demo Credentials (DEMO USE ONLY)

| Account | Username | Password | Scope / Role | Purpose |
|:---|:---|:---|:---|:---|
| **Examiner (Demo)** | `examiner` | `ExaminerPassword123!` | `CSE-BANK-01` / Lead Examiner | Demonstration walkthrough |
| **Administrator** | `admin` | `ExaminerPass123!` | `*` (All Entities) / Admin | Full supervisory access |

> **Warning**: These credentials and keys are provided strictly for local development and demonstration. Change all secrets before any production or formal supervisory evaluation.

---

## Testing & Quality Assurance Suite

All tests can be executed locally without external network access:

### Python Backend Checks & Tests
```bash
# Code style and linting
uv run ruff check .

# Code formatting check
uv run ruff format --check .

# Comprehensive backend test suite (unit, integration, security, performance)
uv run pytest

# Synthetic scenario validation benchmark (10 synthetic worlds)
uv run python -m evaluation.validate_scenarios
```

### Web Frontend Checks & Tests
```bash
# ESLint check
npm --prefix apps/web run lint

# TypeScript static type check
npm --prefix apps/web run typecheck

# Unit and integration tests (Vitest)
npm --prefix apps/web run test -- --run

# Production frontend bundle build
npm --prefix apps/web run build
```

---

## Offline Release Bundling & Air-Gapped Deployment

To package SAT-SA into a self-contained, verifiable offline distribution for air-gapped systems:

```bash
# Build offline zip bundle and signed SHA-256 release manifest
uv run python scripts/build_offline_bundle.py

# Verify cryptographic release integrity against manifest
uv run python scripts/verify_release.py
```

### Containerized Offline Deployment (Docker Compose)
```bash
docker compose -f deploy/compose.yaml up -d
```
The application will be available at `http://127.0.0.1:8080`.

---

## Project Structure

```
sat-sa/
├── apps/
│   ├── api/               # FastAPI backend application, CLI, routes, and services
│   └── web/               # React + TypeScript + Vite frontend application
├── config/                # Policy configurations, detector rules, and verification keys
├── db/                    # SQLAlchemy database models, session factory, Alembic migrations
├── deploy/                # Docker compose, container Dockerfiles, and Hyperledger chaincode
├── docs/                  # Architectural specs, requirements matrix, and audit resolutions
├── evaluation/            # Scenario validation harness and benchmark reports
├── models/                # Sentence encoder manifest and offline tokenizer configurations
├── packages/              # Modular backend domain libraries (analytics, integrity, ingestion, reporting)
├── scripts/               # Operational utilities (model provisioning, demo seeder, verification)
├── storage/               # Preserved runtime directory placeholder (SQLite databases, evidence)
├── synthetic/             # Synthetic evaluation worlds and scenario fixtures
├── pyproject.toml         # Python project specification and dependencies
└── uv.lock                # Pinned Python dependency lockfile
```

---

## Technical & Governance Documentation

- [Requirements Traceability Matrix](docs/SIH26157_REQUIREMENTS_MATRIX.md)
- [Audit Defect Resolution Table](docs/AUDIT_RESOLUTION.md)
- [Architecture & Boundaries Summary](docs/architecture_summary.md)
- [Demonstration Walkthrough Guide](docs/DEMO_WALKTHROUGH.md)
- [Evidence Storage and Hashing](docs/EVIDENCE_STORAGE_AND_HASHING.md)
- [Evidence Trust Model](docs/EVIDENCE_TRUST_MODEL.md)
- [Hyperledger Fabric Ledger Setup](docs/LEDGER_SETUP.md)
- [Model Card (sentence-transformers/all-MiniLM-L6-v2)](docs/model-card.md)
- [Rule Cards](docs/rule-cards.md)
- [Review Policy](docs/review-policy.md)
- [Synthetic Validation & Evaluation](docs/validation.md)
