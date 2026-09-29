"""Lexical fallback similarity engine for SAT-SA.

Engaged when semantic_mode == "auto" and model verification fails or weights are unavailable.
Produces normalized lexical similarity scores in [0.0, 1.0] with explicit labeling and caveats.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import List


@dataclass
class LexicalMatchResult:
    target_idx: int
    candidate_idx: int
    score: float
    method: str = "lexical_fallback"
    fallback_reason: str = "model_unverified_or_unavailable"
    caveats: str = (
        "Lexical fallback used: semantic model unavailable/unverified. "
        "Matches based on keyword and token overlap."
    )


def tokenize(text: str) -> List[str]:
    """Simple alphanumeric tokenizer for lexical comparison."""
    return re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", text.lower())


def compute_lexical_similarity(query: str, doc: str) -> float:
    """Computes a bounded lexical similarity score in [0.0, 1.0] using term overlap and length penalty."""
    q_tokens = tokenize(query)
    d_tokens = tokenize(doc)

    if not q_tokens or not d_tokens:
        return 0.0

    q_counts = Counter(q_tokens)
    d_counts = Counter(d_tokens)

    # Intersection with sublinear term frequency
    intersection_weight = 0.0
    for term, q_cnt in q_counts.items():
        if term in d_counts:
            d_cnt = d_counts[term]
            tf_q = 1.0 + math.log(q_cnt)
            tf_d = 1.0 + math.log(d_cnt)
            intersection_weight += tf_q * tf_d

    # Normalization by length / norm
    norm_q = math.sqrt(sum((1.0 + math.log(c)) ** 2 for c in q_counts.values()))
    norm_d = math.sqrt(sum((1.0 + math.log(c)) ** 2 for c in d_counts.values()))

    if norm_q == 0.0 or norm_d == 0.0:
        return 0.0

    score = intersection_weight / (norm_q * norm_d)
    return min(1.0, max(0.0, float(score)))
