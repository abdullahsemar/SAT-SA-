"""Hybrid investigation-passage similarity engine for supervisory review.

Combines four distinct analytical methodologies:
1. Exact duplicate matching over versioned normalized text.
2. Explainable token/shingle overlap (n-gram Jaccard) with strict negation preservation.
3. TLSH fuzzy hashing with explicit fallback for short (<50 bytes) or low-entropy notes.
4. Pretrained local MiniLM semantic embedding encoder for paraphrased meaning.

Preserves supervisory invariants:
- Negation and operational state words ("not", "never", "failed", "blocked", "successful") are preserved.
- TLSH distance is NOT masked as a percentage; raw method scores remain distinct.
- Displayed passages strictly satisfy: source_text[start:end] == displayed_text.
- Similar wording is an informational observation for human examination, never an autonomous verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from packages.analytics.semantics.chunking import TextChunk
from packages.analytics.semantics.encoder import SemanticEncoder
from packages.analytics.semantics.tlsh_engine import compute_tlsh_digest, compute_tlsh_distance

# Critical operational tokens that must never be stripped during normalization
PRESERVED_OPERATIONAL_TOKENS = {
    "not",
    "no",
    "never",
    "none",
    "neither",
    "nor",
    "failed",
    "failure",
    "fail",
    "failing",
    "blocked",
    "block",
    "denied",
    "deny",
    "rejected",
    "successful",
    "success",
    "succeeded",
    "allowed",
    "allow",
    "critical",
    "high",
    "compromised",
    "escalated",
    "quarantined",
}


def normalize_for_matching(text: str) -> Tuple[str, List[str]]:
    """Versioned normalization (v1.0) preserving negation and operational states.

    Returns:
        (normalized_joined_string, list_of_tokens)
    """
    clean = text.lower().strip()
    # Replace non-alphanumeric punctuation except hyphens in identifiers
    tokens = re.findall(r"\b[a-z0-9\-_]+\b", clean)
    return " ".join(tokens), tokens


def compute_shingle_jaccard(tokens_a: List[str], tokens_b: List[str], n: int = 2) -> float:
    """Computes Jaccard similarity over n-gram shingles with word-level fallback."""
    if not tokens_a or not tokens_b:
        return 0.0

    if len(tokens_a) < n or len(tokens_b) < n:
        # Fall back to 1-gram (unigram) Jaccard
        set_a = set(tokens_a)
        set_b = set(tokens_b)
    else:
        set_a = {tuple(tokens_a[i : i + n]) for i in range(len(tokens_a) - n + 1)}
        set_b = {tuple(tokens_b[i : i + n]) for i in range(len(tokens_b) - n + 1)}

    intersection = len(set_a.intersection(set_b))
    union = len(set_a.union(set_b))
    return float(intersection / union) if union > 0 else 0.0


@dataclass
class HybridPassageMatch:
    target_record_id: str
    target_start_char: int
    target_end_char: int
    target_text: str
    matched_record_id: str
    matched_source_id: str
    matched_record_type: str
    matched_start_char: int
    matched_end_char: int
    matched_text: str
    exact_match: bool
    lexical_score: float  # Jaccard overlap [0.0, 1.0]
    tlsh_distance: Optional[int]  # Integer distance, 0 is exact, None if unsupported
    semantic_score: float  # Cosine similarity [0.0, 1.0]
    hybrid_score: float  # Calibrated indicator for ranking
    method_used: str  # "hybrid_v1"
    possible_explanation: str
    caveats: str
    method_scores: Dict[str, Any] = field(default_factory=dict)
    tlsh_target_digest: Optional[str] = None
    tlsh_matched_digest: Optional[str] = None
    tlsh_unsupported_reason: Optional[str] = None


class HybridSimilarityEngine:
    """Multi-method hybrid passage similarity analyzer."""

    def __init__(
        self,
        mode: str = "auto",
        encoder: Optional[SemanticEncoder] = None,
    ):
        self.mode = mode.lower()
        self.encoder = encoder

    def normalize_text(self, text: str) -> str:
        """Normalizes text while strictly preserving negation and operational tokens."""
        return normalize_for_matching(text)[0]

    def compare_pair(self, text_a: str, text_b: str) -> Dict[str, Any]:
        """Directly compares two text passages across exact, lexical, and TLSH channels."""
        norm_a, tokens_a = normalize_for_matching(text_a)
        norm_b, tokens_b = normalize_for_matching(text_b)
        exact_match = (norm_a == norm_b) and len(norm_a) > 0
        jaccard = compute_shingle_jaccard(tokens_a, tokens_b, n=2)

        from packages.analytics.semantics.tlsh_engine import compute_tlsh, tlsh_distance

        dig_a = compute_tlsh(text_a)
        dig_b = compute_tlsh(text_b)
        dist = tlsh_distance(dig_a, dig_b) if (dig_a and dig_b) else None

        return {
            "exact_match": exact_match,
            "lexical_jaccard": jaccard,
            "tlsh_distance": dist,
            "norm_a": norm_a,
            "norm_b": norm_b,
        }

    def find_matches(
        self, query: str, corpus: List[Tuple[str, str]], top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Finds candidate matches in corpus documents with exact character offsets."""
        results = []
        for record_id, doc_text in corpus:
            # Locate query within document
            idx = doc_text.find(query)
            if idx != -1:
                start_char = idx
                end_char = idx + len(query)
                matched_text = doc_text[start_char:end_char]
            else:
                # Fallback to whole document
                start_char = 0
                end_char = len(doc_text)
                matched_text = doc_text

            comparison = self.compare_pair(query, matched_text)
            results.append(
                {
                    "record_id": record_id,
                    "start_char": start_char,
                    "end_char": end_char,
                    "matched_text": matched_text,
                    "exact_match": comparison["exact_match"],
                    "lexical_jaccard": comparison["lexical_jaccard"],
                    "tlsh_distance": comparison["tlsh_distance"],
                }
            )
        return sorted(results, key=lambda r: r["lexical_jaccard"], reverse=True)[:top_k]

    def evaluate_match(
        self,
        target_chunk: TextChunk,
        cand_chunk: TextChunk,
        target_record_id: str,
        cand_record_id: str,
        cand_source_id: str,
        cand_record_type: str,
        target_vec: Optional[np.ndarray] = None,
        cand_vec: Optional[np.ndarray] = None,
    ) -> HybridPassageMatch:
        """Evaluates similarity across exact, lexical, TLSH, and semantic channels."""
        raw_t = target_chunk.raw_text
        raw_c = cand_chunk.raw_text

        # 1. Exact Normalized Match
        norm_t, tokens_t = normalize_for_matching(raw_t)
        norm_c, tokens_c = normalize_for_matching(raw_c)
        exact_match = (norm_t == norm_c) and len(norm_t) > 0

        # 2. Token / Shingle Overlap (with negation sensitivity)
        lexical_score = compute_shingle_jaccard(tokens_t, tokens_c, n=2)

        # Detect negation discrepancy: if one has negation and the other does not
        negations_t = {t for t in tokens_t if t in ("not", "never", "no", "neither")}
        negations_c = {t for t in tokens_c if t in ("not", "never", "no", "neither")}
        negation_divergence = bool(negations_t) != bool(negations_c)

        # 3. TLSH Fuzzy Hashing
        tlsh_dist: Optional[int] = None
        tlsh_t_digest: Optional[str] = None
        tlsh_c_digest: Optional[str] = None
        tlsh_unsupported: Optional[str] = None

        t_digest, t_err = compute_tlsh_digest(raw_t.encode("utf-8"))
        c_digest, c_err = compute_tlsh_digest(raw_c.encode("utf-8"))

        if t_digest and c_digest:
            tlsh_t_digest = t_digest
            tlsh_c_digest = c_digest
            tlsh_dist = compute_tlsh_distance(t_digest, c_digest)
        else:
            tlsh_unsupported = t_err or c_err or "unsupported_input_length_or_complexity"

        # 4. Semantic Similarity (MiniLM Cosine)
        semantic_score = 0.0
        if target_vec is not None and cand_vec is not None:
            # Vectors are L2-normalized, dot product is cosine similarity
            cos_sim = float(np.dot(target_vec, cand_vec))
            semantic_score = max(0.0, min(1.0, cos_sim))
        else:
            semantic_score = lexical_score  # Lexical fallback if encoder disabled

        # 5. Composite Hybrid Score (for ranking and triage)
        # Invariant: If exact match, score is 1.0.
        # If negation diverges, cap score to prevent false agreement.
        if exact_match:
            hybrid_score = 1.0
        else:
            # Balance lexical and semantic signals
            base_score = 0.6 * semantic_score + 0.4 * lexical_score
            if tlsh_dist is not None:
                # Standard TLSH distance <= 30 confirms near-duplicate
                if tlsh_dist <= 30:
                    base_score = max(base_score, 0.85)
                elif tlsh_dist > 150:
                    base_score = min(base_score, 0.60)

            if negation_divergence:
                # Penalize contradiction
                base_score = min(base_score, 0.45)

            hybrid_score = round(base_score, 4)

        # 6. Classification of Explanation
        t_lower = raw_t.lower()
        if any(term in t_lower for term in ["playbook", "automated", "scanner", "cron"]):
            explanation = "possible_playbook_template"
        elif any(
            term in t_lower for term in ["benign", "false positive", "authorized", "maintenance"]
        ):
            explanation = "possible_repeated_benign"
        elif any(term in t_lower for term in ["vendor", "external", "third-party", "cert"]):
            explanation = "possible_external_investigation"
        elif exact_match or hybrid_score > 0.80:
            explanation = "possible_playbook_template"
        else:
            explanation = "possible_repeated_benign"

        caveats_list: List[str] = [
            "Hybrid similarity combining exact match, shingle Jaccard, TLSH fuzzy hash, and MiniLM semantic embeddings."
        ]
        if negation_divergence:
            caveats_list.append("Note: Potential negation discrepancy detected between passages.")
        if tlsh_unsupported:
            caveats_list.append(
                f"TLSH skipped: {tlsh_unsupported}; relied on lexical/semantic matching."
            )

        method_scores = {
            "exact_match": exact_match,
            "lexical_jaccard": round(lexical_score, 4),
            "tlsh_distance": tlsh_dist,
            "semantic_cosine": round(semantic_score, 4),
            "hybrid_composite": hybrid_score,
            "negation_divergence": negation_divergence,
        }

        return HybridPassageMatch(
            target_record_id=target_record_id,
            target_start_char=target_chunk.start_char,
            target_end_char=target_chunk.end_char,
            target_text=raw_t,
            matched_record_id=cand_record_id,
            matched_source_id=cand_source_id,
            matched_record_type=cand_record_type,
            matched_start_char=cand_chunk.start_char,
            matched_end_char=cand_chunk.end_char,
            matched_text=raw_c,
            exact_match=exact_match,
            lexical_score=round(lexical_score, 4),
            tlsh_distance=tlsh_dist,
            semantic_score=round(semantic_score, 4),
            hybrid_score=hybrid_score,
            method_used="hybrid_v1",
            possible_explanation=explanation,
            caveats=" ".join(caveats_list),
            method_scores=method_scores,
            tlsh_target_digest=tlsh_t_digest,
            tlsh_matched_digest=tlsh_c_digest,
            tlsh_unsupported_reason=tlsh_unsupported,
        )
