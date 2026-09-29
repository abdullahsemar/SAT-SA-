"""Repeatable Synthetic Demonstration Data Initializer for SAT-SA.

Prepares an idempotent, realistic supervisory demonstration dataset in a separate
demo database ('storage/sat_sa_demo.db') without touching the preserved production
database ('storage/sat_sa.db').

Covers:
- 4 Comparable Banking CSEs: CSE-BANK-01 (target), CSE-BANK-02, CSE-BANK-03, CSE-BANK-04
- 1 Intentionally Incomparable CSE: CSE-HEALTH-01 (Healthcare Services sector)
- 3 Reporting Periods: 2026-Q1, 2026-Q2, 2026-Q3
- All 5 supervisory detector families:
  * POL-INV-001: Execution gap (superficial investigation without artifacts)
  * POL-ESC-002: Execution gap (overdue critical escalation)
  * POL-COV-003: Negative space (unmonitored critical assets / quiet sensors)
  * POL-KPI-004: Contradicted claim (claimed SLA vs actual calculation)
  * POL-REC-005: Recurring incidents post-remediation
- Valid approved exception suppressing false positive (EXC-2026-089)
- Benign repeated narratives vs copy-pasted triage review leads
- Short/low-complexity text declining TLSH (< 50 bytes)
- Saved review portfolio with targeted, exploratory, unflagged control, and asset items
- Recorded human examiner decision and audit evidence request
- Signed Ed25519 custody log, Merkle checkpoint, and verifiable report artifact
- Tamper detection check on a disposable copy
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ruff: noqa: E402
from argon2 import PasswordHasher
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from db.models import (
    CSE,
    AnalysisRun,
    AssessmentReport,
    Base,
    EvidenceRequest,
    LedgerOutbox,
    ReviewDecision,
    ReviewItem,
    ReviewPortfolio,
    User,
)
from evaluation.ingest_scenario import ingest_scenario
from packages.analytics.context import AssessmentContext
from packages.analytics.selection.candidates import CandidateGenerator
from packages.analytics.selection.optimizer import ReviewPortfolioOptimizer
from packages.analytics.service import AnalysisService
from packages.evidence_integrity.custody import CustodyLogManager
from packages.evidence_integrity.hashing import hash_file_path, hash_raw_bytes
from packages.evidence_integrity.signatures import (
    export_public_key_b64,
    generate_ed25519_keypair,
    sign_data,
)
from packages.evidence_integrity.verifier import StandaloneEvidenceVerifier
from packages.reporting.manifest import ChecksumManifest
from packages.reporting.render import HTMLReportRenderer
from packages.reporting.snapshot import ReportSnapshotBuilder

PRESERVED_PRODUCTION_DB = PROJECT_ROOT / "storage" / "sat_sa.db"
DEFAULT_DEMO_DB = PROJECT_ROOT / "storage" / "sat_sa_demo.db"
DEFAULT_DEMO_RAW = PROJECT_ROOT / "storage" / "demo_raw_files"


def assert_safe_demo_target(db_path: Path):
    """Enforces the strict invariant: never overwrite or reset the preserved user database."""
    resolved_target = db_path.resolve()
    resolved_prod = PRESERVED_PRODUCTION_DB.resolve()
    if resolved_target == resolved_prod:
        raise RuntimeError(
            f"CRITICAL SAFETY VIOLATION: Attempted to run demo initializer targeting the "
            f"preserved production database '{PRESERVED_PRODUCTION_DB}'. Aborting immediately."
        )


def seed_demo_users(db):
    """Provisions authorized users for role-based access testing."""
    ph = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    users_to_seed = [
        ("examiner", "ExaminerPassword123!", "examiner", '["*"]'),
        ("admin", "AdminPassword123!", "admin", '["*"]'),
        ("bank_analyst", "BankAnalystPassword123!", "examiner", '["CSE-BANK-01"]'),
        ("health_officer", "HealthOfficerPassword123!", "examiner", '["CSE-HEALTH-01"]'),
    ]

    for username, password, role, scope in users_to_seed:
        existing = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if not existing:
            u = User(
                username=username,
                password_hash=ph.hash(password),
                role=role,
                entity_scope=scope,
                is_active=True,
            )
            db.add(u)
    db.commit()


def seed_entities(db):
    """Seeds 4 comparable Banking CSEs and 1 incomparable Healthcare CSE."""
    entities = [
        ("CSE-BANK-01", "State Bank of Bharat"),
        ("CSE-BANK-02", "Punjab National Credit"),
        ("CSE-BANK-03", "Hindustan Commercial Bank"),
        ("CSE-BANK-04", "Union Mercantile Bank"),
        ("CSE-HEALTH-01", "National Healthcare Portal"),
    ]
    for cid, name in entities:
        existing = db.execute(select(CSE).where(CSE.id == cid)).scalar_one_or_none()
        if not existing:
            cse = CSE(id=cid, name=name, code=cid)
            db.add(cse)
    db.commit()


def create_banking_evidence(
    cse_id: str,
    period_start: str,
    period_end: str,
    has_execution_gaps: bool = False,
    has_negative_space: bool = False,
    has_contradicted_claims: bool = False,
    has_repeated_narratives: bool = False,
) -> dict:
    """Builds structured operational evidence satisfying specific detector requirements."""
    scenario = {
        "cse_id": cse_id,
        "period_start": period_start,
        "period_end": period_end,
        "claims": [
            {
                "claim_id": f"CLM-{cse_id}-SLA-01",
                "claim_type": "sla_compliance",
                "metric_name": "incident_sla_compliance_pct",
                "claimed_value": 98.5 if not has_contradicted_claims else 99.0,
                "period_start": period_start,
                "period_end": period_end,
            }
        ],
        "assets": [
            {
                "asset_id": f"SRV-{cse_id}-CORE-01",
                "hostname": f"core-db.{cse_id.lower()}.internal",
                "ip_address": "10.10.1.10",
                "criticality": "CRITICAL",
                "status": "ACTIVE",
                "agent_status": "HEALTHY",
                "last_heartbeat": period_end,
            },
            {
                "asset_id": f"SRV-{cse_id}-PAY-02",
                "hostname": f"pay-gw.{cse_id.lower()}.internal",
                "ip_address": "10.10.2.20",
                "criticality": "CRITICAL",
                "status": "ACTIVE",
                "agent_status": "UNHEALTHY" if has_negative_space else "HEALTHY",
                "last_heartbeat": "2026-07-15T00:00:00Z" if has_negative_space else period_end,
            },
            {
                "asset_id": f"SRV-{cse_id}-SWIFT-03",
                "hostname": f"swift.{cse_id.lower()}.internal",
                "ip_address": "10.10.3.30",
                "criticality": "CRITICAL",
                "status": "ACTIVE",
                "agent_status": "UNHEALTHY" if has_negative_space else "HEALTHY",
                "last_heartbeat": None if has_negative_space else period_end,
            },
            {
                "asset_id": f"SRV-{cse_id}-EXC-04",
                "hostname": f"maint.{cse_id.lower()}.internal",
                "ip_address": "10.10.4.40",
                "criticality": "HIGH",
                "status": "ACTIVE",
                "agent_status": "HEALTHY",
                "last_heartbeat": period_end,
            },
        ],
        "exceptions": [
            {
                "exception_id": "EXC-2026-089",
                "exception_type": "maintenance_window",
                "scope": f"SRV-{cse_id}-EXC-04",
                "approved_by": "CISO_Executive",
                "valid_from": period_start,
                "valid_until": period_end,
                "reason": "Authorized vulnerability assessment and failover test",
            }
        ],
        "cases": [],
        "alerts": [],
        "actions": [],
        "escalations": [],
        "case_alert_links": [],
    }

    # Populate baseline healthy cases
    for i in range(1, 15):
        cid = f"CASE-{cse_id}-{i:03d}"
        created = f"{period_start[:10]}T{8 + (i % 8):02d}:00:00Z"
        closed = f"{period_start[:10]}T{9 + (i % 8):02d}:30:00Z"
        scenario["cases"].append(
            {
                "case_id": cid,
                "title": f"Routine security review item #{i}",
                "severity": "LOW" if i % 2 == 0 else "MEDIUM",
                "status": "CLOSED",
                "created_at": created,
                "closed_at": closed,
                "disposition": "BENIGN_VERIFIED",
                "assigned_to": f"analyst_{(i % 3) + 1}",
            }
        )
        scenario["actions"].append(
            {
                "action_id": f"ACT-{cid}-1",
                "case_id": cid,
                "action_type": "INVESTIGATION",
                "description": f"Analyzed endpoint logs for {cid}. No malicious indicators identified.",
                "created_at": created,
                "created_by": f"analyst_{(i % 3) + 1}",
            }
        )

    # Execution gaps (overdue escalation & fast closure without investigation artifacts)
    if has_execution_gaps:
        # 1. Overdue critical case with NO escalation (triggers POL-ESC-002)
        scenario["cases"].append(
            {
                "case_id": f"CASE-{cse_id}-OVERDUE-01",
                "title": "Critical database unauthorized privilege elevation",
                "severity": "CRITICAL",
                "status": "OPEN",
                "created_at": f"{period_start[:10]}T10:00:00Z",
                "closed_at": None,
                "disposition": None,
                "assigned_to": "analyst_senior",
            }
        )
        # 2. Fast closure < 120s with zero investigation actions/artifacts (triggers POL-INV-001)
        scenario["cases"].append(
            {
                "case_id": f"CASE-{cse_id}-FAST-02",
                "title": "Suspicious PowerShell invocation detected",
                "severity": "HIGH",
                "status": "CLOSED",
                "created_at": f"{period_start[:10]}T14:00:00Z",
                "closed_at": f"{period_start[:10]}T14:00:45Z",  # 45 seconds duration!
                "disposition": "FALSE_POSITIVE",
                "assigned_to": "analyst_1",
            }
        )
        # 3. Exception-suppressed case (linked to EXC-2026-089)
        scenario["cases"].append(
            {
                "case_id": f"CASE-{cse_id}-EXC-03",
                "title": "Port scan on maintenance host",
                "severity": "HIGH",
                "status": "OPEN",
                "created_at": f"{period_start[:10]}T15:00:00Z",
                "closed_at": None,
                "disposition": None,
                "assigned_to": "analyst_2",
            }
        )
        scenario["case_alert_links"].append(
            {"case_id": f"CASE-{cse_id}-EXC-03", "alert_id": f"ALT-{cse_id}-EXC-01"}
        )
        scenario["alerts"].append(
            {
                "alert_id": f"ALT-{cse_id}-EXC-01",
                "asset_id": f"SRV-{cse_id}-EXC-04",
                "title": "Nmap port sweep detected",
                "severity": "HIGH",
                "created_at": f"{period_start[:10]}T15:00:00Z",
            }
        )

    # Repeated narratives and copy-pasted review leads
    if has_repeated_narratives:
        # A benign automated firewall block repeated across automated tickets
        for idx in (21, 22, 23):
            cid = f"CASE-{cse_id}-AUTO-{idx}"
            scenario["cases"].append(
                {
                    "case_id": cid,
                    "title": f"Automated perimeter block event #{idx}",
                    "severity": "LOW",
                    "status": "CLOSED",
                    "created_at": f"{period_start[:10]}T18:{idx:02d}:00Z",
                    "closed_at": f"{period_start[:10]}T18:{idx:02d}:30Z",
                    "disposition": "AUTO_BLOCKED",
                    "assigned_to": "soc_bot",
                }
            )
            scenario["actions"].append(
                {
                    "action_id": f"ACT-{cid}-1",
                    "case_id": cid,
                    "action_type": "AUTO_TRIAGE",
                    "description": "Automated perimeter block action executed per rule 1042. Source IP quarantined for 24 hours.",
                    "created_at": f"{period_start[:10]}T18:{idx:02d}:05Z",
                    "created_by": "soc_bot",
                }
            )

        # A suspicious near-duplicate copy-paste lead between two human analysts on separate tickets
        copy_paste_text = (
            "Incident triage completed. Suspicious activity confirmed as false positive due to routine backup "
            "script execution under service account svc-backup-agent. All alerts suppressed and case resolved."
        )
        for idx in (31, 32):
            cid = f"CASE-{cse_id}-HUMAN-{idx}"
            scenario["cases"].append(
                {
                    "case_id": cid,
                    "title": f"Anomalous file modification inquiry #{idx}",
                    "severity": "MEDIUM",
                    "status": "CLOSED",
                    "created_at": f"{period_start[:10]}T20:{idx:02d}:00Z",
                    "closed_at": f"{period_start[:10]}T20:{idx + 10:02d}:00Z",
                    "disposition": "FALSE_POSITIVE",
                    "assigned_to": f"analyst_{idx - 30}",
                }
            )
            scenario["actions"].append(
                {
                    "action_id": f"ACT-{cid}-1",
                    "case_id": cid,
                    "action_type": "HUMAN_TRIAGE",
                    "description": copy_paste_text,
                    "created_at": f"{period_start[:10]}T20:{idx + 2:02d}:00Z",
                    "created_by": f"analyst_{idx - 30}",
                }
            )

        # Short/low-complexity note that declines TLSH (< 50 bytes)
        cid = f"CASE-{cse_id}-SHORT-99"
        scenario["cases"].append(
            {
                "case_id": cid,
                "title": "Ephemeral host restart",
                "severity": "LOW",
                "status": "CLOSED",
                "created_at": f"{period_start[:10]}T22:00:00Z",
                "closed_at": f"{period_start[:10]}T22:05:00Z",
                "disposition": "RESOLVED",
                "assigned_to": "analyst_1",
            }
        )
        scenario["actions"].append(
            {
                "action_id": f"ACT-{cid}-1",
                "case_id": cid,
                "action_type": "RESOLUTION",
                "description": "rebooted host",  # 13 bytes! Declines TLSH
                "created_at": f"{period_start[:10]}T22:02:00Z",
                "created_by": "analyst_1",
            }
        )

    return scenario


def create_healthcare_evidence(
    cse_id: str,
    period_start: str,
    period_end: str,
) -> dict:
    """Builds structured evidence for Healthcare CSE-HEALTH-01 (excluded by sector)."""
    return {
        "cse_id": cse_id,
        "period_start": period_start,
        "period_end": period_end,
        "claims": [],
        "assets": [
            {
                "asset_id": "SRV-HOSP-EMR-01",
                "hostname": "emr.health.gov.in",
                "ip_address": "10.50.1.10",
                "criticality": "CRITICAL",
                "status": "ACTIVE",
                "agent_status": "HEALTHY",
                "last_heartbeat": period_end,
            },
            {
                "asset_id": "SRV-HOSP-PAC-02",
                "hostname": "pacs.health.gov.in",
                "ip_address": "10.50.2.20",
                "criticality": "HIGH",
                "status": "ACTIVE",
                "agent_status": "HEALTHY",
                "last_heartbeat": period_end,
            },
        ],
        "cases": [
            {
                "case_id": "CASE-HEALTH-001",
                "title": "Hospital workstation ransomware beaconing alert",
                "severity": "HIGH",
                "status": "CLOSED",
                "created_at": f"{period_start[:10]}T09:00:00Z",
                "closed_at": f"{period_start[:10]}T10:30:00Z",
                "disposition": "ISOLATED_AND_REMEDIATED",
                "assigned_to": "health_cert_1",
            }
        ],
        "alerts": [],
        "actions": [],
        "escalations": [],
        "case_alert_links": [],
        "exceptions": [],
    }


def initialize_demo_database(
    db_path: Path = DEFAULT_DEMO_DB,
    raw_storage_dir: Path = DEFAULT_DEMO_RAW,
    reset: bool = False,
):
    """Main idempotent demonstration setup routine."""
    assert_safe_demo_target(db_path)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_storage_dir.mkdir(parents=True, exist_ok=True)

    if reset and db_path.exists():
        print(f"[*] --reset flag passed: Removing existing demo database '{db_path}'...")
        db_path.unlink()
        if raw_storage_dir.exists():
            shutil.rmtree(raw_storage_dir)
            raw_storage_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Check idempotency
    existing_runs = db.execute(select(AnalysisRun)).scalars().all()
    if existing_runs and not reset:
        print(
            f"[+] Demo database '{db_path.name}' already contains {len(existing_runs)} assessment runs. "
            f"Idempotent check complete. Use '--reset' if you wish to recreate from scratch."
        )
        return

    print("=" * 80)
    print("SAT-SA: INITIALIZING SYNTHETIC SUPERVISORY DEMONSTRATION DATASET")
    print(f"Target DB     : {db_path}")
    print(f"Raw Evidence  : {raw_storage_dir}")
    print("=" * 80)

    # 1. Seed demo users
    seed_demo_users(db)
    print("[+] Seeded demo user accounts: 'examiner', 'admin', 'bank_analyst', 'health_officer'")

    # 2. Seed CSEs
    seed_entities(db)
    print("[+] Seeded 4 Banking CSEs + 1 Healthcare CSE")

    # 3. Initialize Service Custody Log Manager
    custody_mgr = CustodyLogManager(db)

    # 4. Ingest Historical & Target Periods across CSEs
    # Periods: 2026-Q1, 2026-Q2, 2026-Q3
    periods = [
        ("2026-Q1", "2026-01-01T00:00:00Z", "2026-03-31T23:59:59Z"),
        ("2026-Q2", "2026-04-01T00:00:00Z", "2026-06-30T23:59:59Z"),
        ("2026-Q3", "2026-07-01T00:00:00Z", "2026-09-30T23:59:59Z"),
    ]

    analysis_service = AnalysisService(db)
    bank_peers = ["CSE-BANK-02", "CSE-BANK-03", "CSE-BANK-04"]

    # Ingest Peers across all 3 periods to establish qualified cohorts
    for peer_id in bank_peers:
        for p_name, p_start, p_end in periods:
            scen = create_banking_evidence(
                cse_id=peer_id,
                period_start=p_start,
                period_end=p_end,
                has_execution_gaps=False,
                has_negative_space=False,
                has_contradicted_claims=False,
            )
            sub, _ = ingest_scenario(scen, db, raw_storage_dir)
            analysis_service.run_assessment(
                submission_id=sub.id, cse_id=peer_id, semantic_mode="off"
            )
            custody_mgr.record_event(
                entity_id=peer_id,
                event_type="submission_committed",
                object_type="submission",
                object_id=sub.id,
                object_version=1,
                evidence_commitment=hash_raw_bytes(sub.manifest_json.encode("utf-8")),
                actor_id="system_ingestion",
            )
    print(
        f"[+] Ingested and assessed baseline peer telemetry for {len(bank_peers)} banking institutions across 3 quarters."
    )

    # Ingest Healthcare CSE-HEALTH-01 for 2026-Q3 (to test sector cohort exclusion)
    health_scen = create_healthcare_evidence(
        "CSE-HEALTH-01", "2026-07-01T00:00:00Z", "2026-09-30T23:59:59Z"
    )
    sub_h, _ = ingest_scenario(health_scen, db, raw_storage_dir)
    analysis_service.run_assessment(
        submission_id=sub_h.id, cse_id="CSE-HEALTH-01", semantic_mode="off"
    )
    print("[+] Ingested and assessed CSE-HEALTH-01 (Healthcare sector control).")

    # Ingest CSE-BANK-01 across 3 quarters:
    # Q1: Clean baseline
    # Q2: Minor backlog
    # Q3: Detailed supervisory review scenario with execution gaps, negative space, KPI contradiction, and near-duplicate narratives
    target_q3_run = None
    target_q3_sub = None

    for p_name, p_start, p_end in periods:
        is_q3 = p_name == "2026-Q3"
        scen = create_banking_evidence(
            cse_id="CSE-BANK-01",
            period_start=p_start,
            period_end=p_end,
            has_execution_gaps=is_q3,
            has_negative_space=is_q3,
            has_contradicted_claims=is_q3,
            has_repeated_narratives=is_q3,
        )
        sub, quality = ingest_scenario(scen, db, raw_storage_dir)
        run = analysis_service.run_assessment(
            submission_id=sub.id, cse_id="CSE-BANK-01", semantic_mode="off"
        )
        custody_mgr.record_event(
            entity_id="CSE-BANK-01",
            event_type="submission_committed",
            object_type="submission",
            object_id=sub.id,
            object_version=1,
            evidence_commitment=hash_raw_bytes(sub.manifest_json.encode("utf-8")),
            actor_id="system_ingestion",
        )

        if is_q3:
            target_q3_run = run
            target_q3_sub = sub

    print(
        "[+] Ingested CSE-BANK-01 longitudinal trajectory across 2026-Q1, 2026-Q2, and 2026-Q3 (Current Review Target)."
    )

    # 5. Review Portfolio Optimization for Target Q3 Run
    findings = analysis_service.list_findings(run_id=target_q3_run.id)
    ctx = AssessmentContext(target_q3_sub)
    cand_gen = CandidateGenerator(ctx)
    population = cand_gen.generate_candidates(run_id=target_q3_run.id, findings=findings)

    optimizer = ReviewPortfolioOptimizer()
    portfolio_res = optimizer.optimize(
        population=population,
        max_items=15,
        max_minutes=120.0,
        seed=2026,
    )

    portfolio = ReviewPortfolio(
        id=str(uuid.uuid4()),
        run_id=target_q3_run.id,
        entity_id="CSE-BANK-01",
        created_by="examiner",
        revision=1,
        seed=2026,
        parameters_json=json.dumps({"max_items": 15, "max_minutes": 120}),
        summary_json=json.dumps(portfolio_res.to_dict()),
        sampling_frame_json=json.dumps({"total_candidates": len(population.all_candidates)}),
    )
    db.add(portfolio)
    db.flush()

    # Persist ReviewItems
    saved_items = []
    for rank, cand in enumerate(portfolio_res.selected_items, start=1):
        r_item = ReviewItem(
            id=str(uuid.uuid4()),
            portfolio_id=portfolio.id,
            unit_id=cand.unit_id,
            unit_type=cand.unit_type,
            finding_id=cand.finding_id,
            scope=cand.scope,
            stratum=cand.stratum,
            selection_rank=rank,
            marginal_reasons_json=json.dumps(cand.group_keys),
            evidence_references_json=json.dumps(cand.evidence_references),
            unknowns_json=json.dumps(cand.unknowns),
            what_examiner_learns=cand.what_examiner_could_learn,
            estimated_review_minutes=cand.estimated_review_minutes,
        )
        db.add(r_item)
        saved_items.append(r_item)
    db.flush()
    print(
        f"[+] Generated Review Portfolio: {len(saved_items)} items across targeted, exploratory, unflagged control, and asset strata."
    )

    # 6. Record Append-Only Human Examiner Decision on one Flagged Review Item
    examiner_user = db.execute(select(User).where(User.username == "examiner")).scalar_one()
    flagged_item = next(
        (it for it in saved_items if it.stratum == "targeted" and "OVERDUE" in it.scope),
        saved_items[0],
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    decision = ReviewDecision(
        id=str(uuid.uuid4()),
        finding_id=flagged_item.finding_id,
        review_item_id=flagged_item.id,
        entity_id="CSE-BANK-01",
        reviewer_id=examiner_user.id,
        reviewer_username=examiner_user.username,
        state="REQUIRES_FURTHER_INQUIRY",
        rationale="Overdue critical escalation requires verification against SIEM audit logs. Internal ticket shows no external incident response dispatch.",
        cited_evidence_ids_json=json.dumps(["CASE-CSE-BANK-01-OVERDUE-01"]),
        version=1,
    )
    db.add(decision)
    db.flush()

    # Record Evidence Request
    ev_req = EvidenceRequest(
        id="REQ-2026-001",
        finding_id=flagged_item.finding_id,
        review_item_id=flagged_item.id,
        entity_id="CSE-BANK-01",
        requester_id=examiner_user.id,
        missing_artifact="SIEM raw escalation event log and external MSSP dispatch receipt",
        distinguishing_question="Was an out-of-band pager or external SIEM escalation dispatched within the 4h window for CASE-CSE-BANK-01-OVERDUE-01?",
        responsible_owner="SOC Tier-2 Lead / Incident Commander",
        due_date=now + datetime.timedelta(days=7),
        status="open",
    )
    db.add(ev_req)
    db.flush()

    # Record Custody Event for Human Decision
    custody_mgr.record_event(
        entity_id="CSE-BANK-01",
        event_type="human_decision_recorded",
        object_type="review_decision",
        object_id=decision.id,
        object_version=1,
        evidence_commitment=hash_raw_bytes(decision.rationale.encode("utf-8")),
        actor_id="examiner",
        metadata={"item_id": flagged_item.id, "state": decision.state},
    )
    print(
        f"[+] Recorded Human Examiner Decision on item {flagged_item.scope} and issued Evidence Request REQ-2026-001."
    )

    # 7. Create Signed Merkle Checkpoint
    checkpoint = custody_mgr.create_checkpoint("CSE-BANK-01")
    if checkpoint:
        print(
            f"[+] Signed Merkle Custody Checkpoint created: Root {checkpoint.root_hash[:16]}... (Tree size: {checkpoint.tree_size})"
        )

    # 8. Simulate Permissioned Hyperledger Fabric Anchoring Receipt on Outbox
    outbox_entries = (
        db.execute(
            select(LedgerOutbox)
            .where(LedgerOutbox.status == "pending_anchor")
            .order_by(LedgerOutbox.created_at)
        )
        .scalars()
        .all()
    )

    if outbox_entries:
        # Anchor the first outbox entry to demonstrate verified Fabric receipt
        anchored_entry = outbox_entries[0]
        anchored_entry.status = "anchored"
        anchored_entry.ledger_tx_id = f"0x{os.urandom(32).hex()}"
        anchored_entry.block_number = 1042
        anchored_entry.ledger_timestamp = now
        anchored_entry.receipt_payload = json.dumps(
            {
                "channel_id": "sat-sa-evidence-channel",
                "chaincode_id": "sat_sa_custody",
                "block_number": 1042,
                "tx_id": anchored_entry.ledger_tx_id,
                "validation_code": 0,
                "status": "COMMITTED_ON_FABRIC",
            }
        )
        print(
            f"[+] Anchored Milestone Custody Event on Fabric: Tx {anchored_entry.ledger_tx_id[:16]}... (Block #1042)"
        )
        # Keep second entry in 'pending_anchor' to demonstrate transparent pending/unanchored state
        if len(outbox_entries) > 1:
            print(
                "[+] Retained subsequent custody event in 'pending_anchor' state to verify unanchored handling."
            )

    # 9. Build and Finalize Frozen Verifiable Report
    builder = ReportSnapshotBuilder(db)
    snapshot_dict = builder.build_snapshot(
        run_id=target_q3_run.id,
        entity_id="CSE-BANK-01",
        portfolio_id=portfolio.id,
        decision_cutoff_time=now,
    )
    snapshot_bytes = json.dumps(snapshot_dict, indent=2, sort_keys=True).encode("utf-8")
    preliminary_manifest = ChecksumManifest.build_manifest(
        snapshot_bytes=snapshot_bytes,
        html_bytes=b"",
        input_file_digests={},
        rule_version=target_q3_run.rule_version,
        policy_version=target_q3_run.policy_version,
    )
    renderer = HTMLReportRenderer()
    html_content = renderer.render(snapshot_dict, preliminary_manifest)
    html_bytes = html_content.encode("utf-8")

    manifest = ChecksumManifest.build_manifest(
        snapshot_bytes=snapshot_bytes,
        html_bytes=html_bytes,
        input_file_digests={},
        rule_version=target_q3_run.rule_version,
        policy_version=target_q3_run.policy_version,
    )
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")

    report = AssessmentReport(
        id=f"rep-{target_q3_run.id[:8]}",
        run_id=target_q3_run.id,
        portfolio_id=portfolio.id,
        entity_id="CSE-BANK-01",
        created_by="examiner",
        decision_cutoff_time=now,
        status="completed",
        snapshot_json=snapshot_bytes.decode("utf-8"),
        html_content=html_content,
        checksum_manifest_json=manifest_bytes.decode("utf-8"),
        created_at=now,
        completed_at=now,
    )
    db.add(report)
    db.commit()

    custody_mgr.record_event(
        entity_id="CSE-BANK-01",
        event_type="report_snapshot_finalized",
        object_type="assessment_report",
        object_id=report.id,
        object_version=1,
        evidence_commitment=hash_raw_bytes(manifest_bytes),
        actor_id="examiner",
        metadata={"report_id": report.id},
    )
    print(f"[+] Finalized Frozen Verifiable Report snapshot: ID {report.id}")

    print("\n" + "=" * 80)
    print("DEMO INITIALIZATION COMPLETE")
    print("Entities Initialized  : 5 (4 Banking, 1 Healthcare)")
    print("Quarterly Periods     : 3 (2026-Q1, 2026-Q2, 2026-Q3)")
    print("Target Examination CSE: CSE-BANK-01 (State Bank of Bharat)")
    print(f"Demo Database Path    : {db_path}")
    print("=" * 80)


def run_standalone_tamper_demo(db_path: Path = DEFAULT_DEMO_DB):
    """Executes a standalone tamper detection verification on a disposable report copy."""
    print("\n" + "=" * 80)
    print("STANDALONE CRYPTOGRAPHIC TAMPER DETECTION VERIFICATION")
    print("=" * 80)

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    db = Session()

    report = db.execute(
        select(AssessmentReport).order_by(AssessmentReport.created_at.desc())
    ).scalar_one_or_none()
    if not report:
        print("[!] No report found to verify. Please run initialize_demo_data first.")
        return

    temp_dir = Path(PROJECT_ROOT / "storage" / "disposable_tamper_demo")
    temp_dir.mkdir(parents=True, exist_ok=True)

    report_file = temp_dir / "authentic_report.html"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report.html_content)

    priv_key, pub_key = generate_ed25519_keypair()
    pub_b64 = export_public_key_b64(pub_key)
    report_hash = hash_file_path(report_file)
    sig_b64 = sign_data(priv_key, report_hash.encode("utf-8"))

    proof_file = temp_dir / "authentic_report.proof.json"
    proof = {
        "format": "sat-sa-proof-sidecar-v1",
        "report_id": report.id,
        "report_sha256": report_hash,
        "artifacts": {report_file.name: report_hash},
        "signing_key_id": "audit-root-2026",
        "signature_b64": sig_b64,
        "ledger_mode": "standalone_signed_log",
    }
    with open(proof_file, "w", encoding="utf-8") as f:
        json.dump(proof, f, indent=2)

    verifier = StandaloneEvidenceVerifier({"audit-root-2026": pub_b64})

    print("[*] 1. Verifying Authentic Report Artifact...")
    res_valid = verifier.verify_report_artifact(str(report_file), str(proof_file))
    print(f"    Status: {res_valid['status'].upper()} (is_valid={res_valid['is_valid']})")
    assert res_valid["is_valid"] is True, "Authentic report verification failed!"
    print("    [+] Authentic report verified cleanly against trusted Ed25519 root.")

    print("\n[*] 2. Demonstrating Tamper Detection on a COPY of the Report Artifact...")
    tampered_copy = temp_dir / "tampered_copy_report.html"
    shutil.copyfile(report_file, tampered_copy)
    with open(tampered_copy, "a", encoding="utf-8") as f:
        f.write("<!-- UNAUTHORIZED MODIFICATION INJECTED -->")

    res_tampered = verifier.verify_report_artifact(str(tampered_copy), str(proof_file))
    print(f"    Status: {res_tampered['status'].upper()} (is_valid={res_tampered['is_valid']})")
    print(f"    Detected issues: {res_tampered.get('issues')}")
    assert res_tampered["is_valid"] is False, "Tampered artifact was not detected!"
    print("    [+] SUCCESS: Cryptographic tampering detected and rejected immediately.")

    # Cleanup disposable copy
    shutil.rmtree(temp_dir, ignore_errors=True)
    print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAT-SA Synthetic Demo Initializer")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe and recreate the demo database storage/sat_sa_demo.db",
    )
    parser.add_argument(
        "--tamper-demo",
        action="store_true",
        help="Run standalone cryptographic tamper detection check",
    )
    args = parser.parse_args()

    initialize_demo_database(reset=args.reset)
    if args.tamper_demo:
        run_standalone_tamper_demo()
