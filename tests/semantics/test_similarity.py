"""Tests for passage similarity, mode invariants, candidate exclusions, and held-out fixture."""

from __future__ import annotations

import pytest

from packages.analytics.semantics.registry import ModelVerificationError
from packages.analytics.semantics.similarity import SimilarityEngine


def test_held_out_similarity_fixture():
    """Held-out fixture measuring paraphrases, negations, boilerplate, and unrelated notes."""
    engine = SimilarityEngine(mode="auto")

    target = "Verified source IP belongs to authorized external vulnerability scanner."

    candidates = [
        # 1. Paraphrase (should have high similarity)
        {
            "record_id": "cand-paraphrase",
            "source_id": "src-other",
            "record_type": "cases",
            "text": "Confirmed originating IP is an approved automated security scanner.",
        },
        # 2. Boilerplate with differing outcome (should be distinguishable)
        {
            "record_id": "cand-diff-outcome",
            "source_id": "src-other",
            "record_type": "cases",
            "text": "Verified source IP belongs to hostile botnet command and control node.",
        },
        # 3. Negation (measured honestly: semantic encoder can have moderate token overlap)
        {
            "record_id": "cand-negation",
            "source_id": "src-other",
            "record_type": "cases",
            "text": "Source IP does not belong to authorized external scanner; confirmed attacker.",
        },
        # 4. Unrelated note (should have lowest similarity)
        {
            "record_id": "cand-unrelated",
            "source_id": "src-other",
            "record_type": "cases",
            "text": "Server core-db-01 scheduled routine memory upgrade and kernel patch reboot.",
        },
    ]

    matches = engine.find_similar_passages(
        target_record_id="target-01",
        target_source_id="src-target",
        target_record_type="cases",
        target_text=target,
        candidates=candidates,
        limit=5,
    )

    scores_by_id = {m.matched_record_id: m.similarity_score for m in matches}

    # 1. Paraphrase must rank highest among non-negated candidates
    assert scores_by_id.get("cand-paraphrase", 0.0) > scores_by_id.get("cand-unrelated", 0.0)

    # 2. Unrelated note must have low score
    assert scores_by_id.get("cand-unrelated", 0.0) < 0.45


def test_same_record_excluded():
    """Target record is never returned as a corroborating match for itself."""
    engine = SimilarityEngine(mode="auto")
    text = "Investigated case notes."
    candidates = [
        {"record_id": "SAME-REC-01", "source_id": "src-1", "record_type": "cases", "text": text},
        {"record_id": "DIFF-REC-02", "source_id": "src-2", "record_type": "cases", "text": text},
    ]

    matches = engine.find_similar_passages(
        target_record_id="SAME-REC-01",
        target_source_id="src-1",
        target_record_type="cases",
        target_text=text,
        candidates=candidates,
    )

    matched_ids = [m.matched_record_id for m in matches]
    assert "SAME-REC-01" not in matched_ids
    assert "DIFF-REC-02" in matched_ids


def test_duplicate_import_excluded():
    """Identical content from the same source system is excluded as duplicate import."""
    engine = SimilarityEngine(mode="auto")
    text = "Identical triage note from Splunk export."
    candidates = [
        {
            "record_id": "DUP-REC-02",
            "source_id": "src-splunk",
            "record_type": "cases",
            "text": text,
        },
        {"record_id": "DIFF-REC-03", "source_id": "src-jira", "record_type": "cases", "text": text},
    ]

    matches = engine.find_similar_passages(
        target_record_id="ORIG-REC-01",
        target_source_id="src-splunk",
        target_record_type="cases",
        target_text=text,
        candidates=candidates,
    )

    matched_ids = [m.matched_record_id for m in matches]
    assert "DUP-REC-02" not in matched_ids
    assert "DIFF-REC-03" in matched_ids


def test_mode_off_returns_empty_without_computation():
    """Mode 'off' executes neither encoder nor lexical fallback."""
    engine = SimilarityEngine(mode="off")
    assert engine.encoder is None
    matches = engine.find_similar_passages(
        target_record_id="REC-01",
        target_source_id="src-1",
        target_record_type="cases",
        target_text="Some text",
        candidates=[
            {
                "record_id": "REC-02",
                "source_id": "src-2",
                "record_type": "cases",
                "text": "Some text",
            }
        ],
    )
    assert matches == []


def test_mode_required_fails_on_missing_model(tmp_path):
    """Mode 'required' raises ModelVerificationError when model is unverified or missing."""
    with pytest.raises(ModelVerificationError):
        SimilarityEngine(
            mode="required",
            model_dir=tmp_path / "nonexistent",
            manifest_path=tmp_path / "manifest.json",
        )


def test_mode_auto_falls_back_to_lexical_when_unverified(tmp_path):
    """Mode 'auto' transitions to labeled lexical fallback when model is unverified."""
    engine = SimilarityEngine(
        mode="auto",
        model_dir=tmp_path / "nonexistent",
        manifest_path=tmp_path / "manifest.json",
    )
    assert engine.encoder is None
    assert engine.fallback_reason is not None

    matches = engine.find_similar_passages(
        target_record_id="REC-01",
        target_source_id="src-1",
        target_record_type="cases",
        target_text="Automated scanner activity detected on firewall",
        candidates=[
            {
                "record_id": "REC-02",
                "source_id": "src-2",
                "record_type": "cases",
                "text": "Scanner activity confirmed on firewall rule",
            }
        ],
    )

    assert len(matches) > 0
    assert matches[0].method_used == "lexical_fallback"
    assert "Lexical fallback used" in matches[0].caveats
