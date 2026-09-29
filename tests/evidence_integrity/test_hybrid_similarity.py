"""Tests for hybrid similarity: exact match, lexical Jaccard, TLSH fuzzy hashing, and semantic evaluation."""

from packages.analytics.semantics.near_duplicates import HybridSimilarityEngine
from packages.analytics.semantics.tlsh_engine import compute_tlsh, tlsh_distance


def test_tlsh_short_and_low_complexity_rejection():
    # Very short input (< 50 bytes) must return None without artificial padding
    short_text = "Benign alert"
    assert compute_tlsh(short_text) is None

    # Low entropy input (repetitive identical characters) must return None
    repetitive_text = "A" * 100
    assert compute_tlsh(repetitive_text) is None


def test_tlsh_distance_computation():
    text1 = (
        "Investigation concluded that host 192.168.1.50 was compromised via spear phishing email "
        "containing malicious macro attachment. The user executed payload at 09:30 AM resulting in beaconing."
    )
    text2 = (
        "Investigation concluded that host 192.168.1.55 was compromised via spear phishing email "
        "containing malicious macro attachment. The user executed payload at 10:15 AM resulting in beaconing."
    )
    digest1 = compute_tlsh(text1)
    digest2 = compute_tlsh(text2)

    assert digest1 is not None
    assert digest2 is not None
    assert digest1.startswith("T1")
    assert digest2.startswith("T1")

    dist = tlsh_distance(digest1, digest2)
    assert dist is not None
    # Near duplicate variations have low distance (< 100)
    assert dist < 100


def test_negation_and_operational_words_preservation():
    engine = HybridSimilarityEngine()

    text_success = "Malicious executable execution was successful on workstation."
    text_blocked = "Malicious executable execution was blocked and failed on workstation."

    norm_success = engine.normalize_text(text_success)
    norm_blocked = engine.normalize_text(text_blocked)

    # Operational words must be preserved
    assert "successful" in norm_success
    assert "blocked" in norm_blocked
    assert "failed" in norm_blocked

    # They should not produce an exact match
    res = engine.compare_pair(text_success, text_blocked)
    assert res["exact_match"] is False


def test_hybrid_similarity_exact_match():
    engine = HybridSimilarityEngine()
    text = "Confirmed unauthorized access using stolen credentials from internal VPN gateway."
    res = engine.compare_pair(text, text)

    assert res["exact_match"] is True
    assert res["lexical_jaccard"] == 1.0


def test_exact_character_span_integrity():
    engine = HybridSimilarityEngine()
    corpus_document = (
        "Incident Record ID: 8849. "
        "Analyst notes state that phishing campaign targeted finance department on Monday morning. "
        "Follow up ticket opened with network operations team."
    )
    query_target = "phishing campaign targeted finance department on Monday morning."

    matches = engine.find_matches(query_target, [("rec-1", corpus_document)], top_k=1)
    assert len(matches) > 0
    match = matches[0]

    start = match["start_char"]
    end = match["end_char"]
    # Invariant: source_text[start:end] == matched_text
    assert corpus_document[start:end] == match["matched_text"]
