"""Validation evaluation harness for the 10 synthetic operational scenarios.

Evaluates detector behavior, false concern rates, and review portfolio allocation
across 10 synthetic worlds without leaking scenario IDs or latent labels to analytics.
Enforces explicit expected outcomes (rules, object scopes, evidence states, citations)
and exits nonzero on any acceptance failure.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base
from evaluation.citations import validate_citations
from evaluation.ingest_scenario import ingest_scenario
from packages.analytics.context import AssessmentContext
from packages.analytics.selection.candidates import CandidateGenerator
from packages.analytics.selection.optimizer import ReviewPortfolioOptimizer
from packages.analytics.service import AnalysisService


def run_scenario_evaluation(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Runs a single scenario through the full analytics pipeline."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    scenario_id = scenario["scenario_id"]
    name = scenario["name"]
    cse_id = scenario.get("cse_id", "CSE-BANK-01")
    latent_truth = scenario.get("latent_truth", {})
    expected_outcomes = scenario.get("expected_outcomes", {})

    storage = tempfile.TemporaryDirectory(prefix="sat-sa-evaluation-")
    sub, quality = ingest_scenario(scenario, db, Path(storage.name))

    # 3. Execute Assessment Analysis (No access to latent truth or expected outcomes)
    analysis_service = AnalysisService(db)
    run = analysis_service.run_assessment(
        submission_id=sub.id,
        cse_id=cse_id,
        semantic_mode="off",  # deterministic baseline
    )

    findings = analysis_service.list_findings(run_id=run.id)

    # 4. Review Portfolio Generation
    ctx = AssessmentContext(sub)
    cand_gen = CandidateGenerator(ctx)
    population = cand_gen.generate_candidates(run_id=run.id, findings=findings)

    optimizer = ReviewPortfolioOptimizer()
    portfolio_res = optimizer.optimize(
        population=population,
        max_items=5,
        strata_allocation={"targeted": 3, "control": 1, "exploratory": 1},
        seed=42,
    )

    # 5. Honest Metric & Outcome Classification (per B1 & B2)
    # Distinguish adverse findings (potential_concern, contradicted) from non-adverse / uncertainty
    adverse_findings = [
        f
        for f in findings
        if f.evidence_state in ("potential_concern", "contradicted", "contradictory")
    ]
    insufficient_evidence_findings = [
        f for f in findings if f.evidence_state == "insufficient_evidence"
    ]
    supported_findings = [f for f in findings if f.evidence_state == "supported"]

    is_control = latent_truth.get("is_control", False)

    # Evaluate explicit expected outcomes
    expected_findings_spec = expected_outcomes.get("expected_findings", [])
    prohibited_adverse_rules = set(expected_outcomes.get("prohibited_adverse_rules", []))

    missing_expected_findings: List[Dict[str, Any]] = []
    incorrect_evidence_states: List[Dict[str, Any]] = []
    broken_citations = validate_citations(findings, db, sub)

    for exp in expected_findings_spec:
        exp_rule = exp["rule_id"]
        exp_obj = exp.get("primary_object_id")
        acceptable_states = set(exp.get("acceptable_states", []))

        # Look for matching actual finding
        matching = [
            f
            for f in findings
            if f.rule_id == exp_rule and (not exp_obj or f.primary_object_id == exp_obj)
        ]
        if not matching:
            missing_expected_findings.append(
                {
                    "rule_id": exp_rule,
                    "primary_object_id": exp_obj,
                    "expected_states": list(acceptable_states),
                    "reason": "Finding not produced by detector",
                }
            )
        else:
            for found in matching:
                if acceptable_states and found.evidence_state not in acceptable_states:
                    incorrect_evidence_states.append(
                        {
                            "rule_id": exp_rule,
                            "primary_object_id": exp_obj,
                            "finding_id": found.id,
                            "actual_state": found.evidence_state,
                            "acceptable_states": list(acceptable_states),
                        }
                    )
    # Unexpected adverse findings: any adverse finding whose rule was prohibited or not declared
    unexpected_adverse_findings: List[Dict[str, Any]] = []
    for f in adverse_findings:
        expected_adverse = any(
            e["rule_id"] == f.rule_id
            and (not e.get("primary_object_id") or e["primary_object_id"] == f.primary_object_id)
            and f.evidence_state in e.get("acceptable_states", [])
            for e in expected_findings_spec
        )
        if f.rule_id in prohibited_adverse_rules or not expected_adverse:
            reason = (
                f"Rule {f.rule_id} prohibited from reaching adverse conclusion in this scenario"
                if f.rule_id in prohibited_adverse_rules
                else f"Adverse finding on rule {f.rule_id} was not declared in expected_findings"
            )
            unexpected_adverse_findings.append(
                {
                    "rule_id": f.rule_id,
                    "primary_object_id": f.primary_object_id,
                    "evidence_state": f.evidence_state,
                    "rationale": f.rationale,
                    "reason": reason,
                }
            )

    has_mismatch = bool(
        missing_expected_findings
        or incorrect_evidence_states
        or unexpected_adverse_findings
        or broken_citations
        or (
            expected_outcomes.get("expected_adverse_findings_count") is not None
            and len(adverse_findings) != expected_outcomes["expected_adverse_findings_count"]
        )
        or (
            expected_outcomes.get("expected_unknown_findings_count") is not None
            and len(insufficient_evidence_findings)
            != expected_outcomes["expected_unknown_findings_count"]
        )
    )
    status = "FAIL" if has_mismatch else "PASS"

    explanation = []
    if missing_expected_findings:
        explanation.append(f"Missing expected: {len(missing_expected_findings)}")
    if incorrect_evidence_states:
        explanation.append(f"Incorrect states: {len(incorrect_evidence_states)}")
    if unexpected_adverse_findings:
        explanation.append(f"Unexpected adverse: {len(unexpected_adverse_findings)}")
    if broken_citations:
        explanation.append(f"Broken citations: {len(broken_citations)}")
    if (
        expected_outcomes.get("expected_adverse_findings_count") is not None
        and len(adverse_findings) != expected_outcomes["expected_adverse_findings_count"]
    ):
        explanation.append(
            f"Adverse count mismatch: expected {expected_outcomes['expected_adverse_findings_count']}, got {len(adverse_findings)}"
        )
    if (
        expected_outcomes.get("expected_unknown_findings_count") is not None
        and len(insufficient_evidence_findings)
        != expected_outcomes["expected_unknown_findings_count"]
    ):
        explanation.append(
            f"Unknown count mismatch: expected {expected_outcomes['expected_unknown_findings_count']}, got {len(insufficient_evidence_findings)}"
        )
    if not explanation:
        explanation.append("All scenario expectations satisfied.")

    db.close()
    engine.dispose()
    storage.cleanup()
    return {
        "intake_quality": {"accepted": quality.accepted_count, "rejected": quality.rejected_count},
        "scenario_id": scenario_id,
        "name": name,
        "is_control": is_control,
        "expected_outcomes": expected_outcomes,
        "actual_findings": [
            {
                "rule_id": f.rule_id,
                "primary_object_type": f.primary_object_type,
                "primary_object_id": f.primary_object_id,
                "evidence_state": f.evidence_state,
                "severity": f.severity,
            }
            for f in findings
        ],
        "adverse_findings_count": len(adverse_findings),
        "insufficient_evidence_count": len(insufficient_evidence_findings),
        "supported_findings_count": len(supported_findings),
        "missing_expected_findings": missing_expected_findings,
        "unexpected_adverse_findings": unexpected_adverse_findings,
        "incorrect_evidence_states": incorrect_evidence_states,
        "broken_citations": broken_citations,
        "explanation": "; ".join(explanation),
        "portfolio_items_selected": len(portfolio_res.selected_items),
        "covered_hypotheses": list(
            set(h for item in portfolio_res.selected_items for h in item.hypothesis_links)
        ),
        "shortfalls": portfolio_res.shortfalls,
        "status": status,
    }


def main():
    scenario_file = (
        Path(__file__).resolve().parent.parent / "synthetic" / "scenarios" / "final-validation.json"
    )
    if not scenario_file.is_file():
        raise FileNotFoundError(f"Scenario file not found: {scenario_file}")

    with open(scenario_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    worlds = data.get("worlds", [])
    results: List[Dict[str, Any]] = []

    print(f"Executing validation across {len(worlds)} synthetic worlds...")
    any_failed = False
    for w in worlds:
        res = run_scenario_evaluation(w)
        results.append(res)
        tag = f"[{res['status']}]"
        print(
            f"{tag} [{res['scenario_id']}] {res['name']}: "
            f"{res['adverse_findings_count']} adverse, "
            f"{res['insufficient_evidence_count']} unknown, "
            f"{res['supported_findings_count']} supported | {res['explanation']}"
        )
        if res["status"] != "PASS":
            any_failed = True

    # Metrics defined per B2:
    # Evaluation unit: Scenario-level operational state and finding-level detection
    total_scenarios = len(results)
    controls = [r for r in results if r["is_control"] and r["insufficient_evidence_count"] == 0]
    unknown_controls = [
        r for r in results if r["is_control"] and r["insufficient_evidence_count"] > 0
    ]
    non_controls = [r for r in results if not r["is_control"]]

    # Control Specificity: True Negatives / All Controls
    # A control world is a True Negative if it has 0 adverse findings (potential_concern or contradicted).
    # Any adverse finding on a control is a False Positive.
    true_negatives = sum(
        1 for r in controls if r["adverse_findings_count"] == 0 and r["status"] == "PASS"
    )
    false_positives = len(controls) - true_negatives
    control_specificity = round(true_negatives / len(controls), 4) if len(controls) > 0 else "N/A"

    # Non-control Sensitivity:
    # Distinguish:
    # - Assessable non-controls: where evidence permitted determining the condition (worlds where expected adverse findings were defined)
    # - Unassessable / Incomplete evidence non-controls: where operational condition exists but evidence was biased/omitted
    assessable_non_controls = [
        r
        for r in non_controls
        if r["expected_outcomes"].get("expected_adverse_findings_count", 0) > 0
    ]
    unassessable_non_controls = [
        r
        for r in non_controls
        if r["expected_outcomes"].get("expected_adverse_findings_count", 0) == 0
    ]

    # In assessable non-controls: TP is where expected adverse finding was detected
    true_positives = sum(
        1
        for r in assessable_non_controls
        if r["adverse_findings_count"] > 0 and r["status"] == "PASS"
    )
    false_negatives = len(assessable_non_controls) - true_positives
    detection_sensitivity = (
        round(true_positives / len(assessable_non_controls), 4)
        if len(assessable_non_controls) > 0
        else "N/A"
    )

    passed_scenarios = sum(1 for r in results if r["status"] == "PASS")
    failed_scenarios = total_scenarios - passed_scenarios

    report = {
        "evaluation_timestamp": datetime.now().isoformat(),
        "total_worlds_evaluated": total_scenarios,
        "scenarios_passed": passed_scenarios,
        "scenarios_failed": failed_scenarios,
        "evaluation_granularity": "scenario_and_obligation_object",
        "control_worlds": {
            "total_controls": len(controls),
            "true_negatives": true_negatives,
            "false_positives": false_positives,
            "numerator": true_negatives,
            "denominator": len(controls),
            "specificity": control_specificity,
            "unassessable_controls": len(unknown_controls),
        },
        "non_control_worlds": {
            "total_non_controls": len(non_controls),
            "assessable_non_controls": len(assessable_non_controls),
            "true_positives": true_positives,
            "false_negatives": false_negatives,
            "numerator": true_positives,
            "denominator": len(assessable_non_controls),
            "sensitivity_assessable": detection_sensitivity,
            "unassessable_due_to_incomplete_evidence": len(unassessable_non_controls),
        },
        "disclaimer": (
            "NOTICE: Synthetic scenario evaluation tests system consistency against declared latent models and synthetic fixture performance. "
            "It does not constitute a statistical claim of expert-equivalent supervisory efficacy or real-world SOC effectiveness accuracy."
        ),
        "world_results": results,
    }

    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "validation_report.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    sens_str = (
        f"{true_positives}/{len(assessable_non_controls)} ({detection_sensitivity})"
        if len(assessable_non_controls) > 0
        else "N/A"
    )
    spec_str = (
        f"{true_negatives}/{len(controls)} ({control_specificity})" if len(controls) > 0 else "N/A"
    )

    print(f"\nValidation complete. Report written to {out_file}")
    print(
        f"Passed: {passed_scenarios}/{total_scenarios} | "
        f"Sensitivity (Assessable): {sens_str} | "
        f"Specificity (Controls): {spec_str} | "
        f"Unassessable (Incomplete Evidence): {len(unassessable_non_controls)}"
    )

    if any_failed:
        print("ERROR: One or more synthetic validation scenarios failed acceptance expectations.")
        sys.exit(1)


if __name__ == "__main__":
    main()
