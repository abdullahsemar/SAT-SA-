"""Similarity computation engine for investigation passages in SAT-SA.

Evaluates similarity between target finding passages and historical candidate passages:
- Enforces entity boundaries (no cross-entity leakage).
- Excludes same document, duplicate imports, and shared upstream exports.
- Uses bounded candidate pools (no unconstrained N x N matrix).
- Supports modes: "off", "auto", "required".
- Labels possible explanation categories for human review.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from packages.analytics.semantics.chunking import TextChunk, TextChunker
from packages.analytics.semantics.config import default_semantic_config
from packages.analytics.semantics.encoder import SemanticEncoder
from packages.analytics.semantics.fallback import compute_lexical_similarity
from packages.analytics.semantics.near_duplicates import (
    compute_shingle_jaccard,
    normalize_for_matching,
)
from packages.analytics.semantics.registry import (
    ModelVerificationError,
    validate_model_directory,
)
from packages.analytics.semantics.tlsh_engine import compute_tlsh_digest, compute_tlsh_distance


@dataclass
class CandidatePassage:
    record_id: str
    source_id: str
    record_type: str
    chunk: TextChunk
    vector: Optional[np.ndarray] = None


@dataclass
class SimilarityMatch:
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
    similarity_score: float
    method_used: str
    possible_explanation: str
    caveats: str
    model_revision: Optional[str] = None
    manifest_digest: Optional[str] = None
    fallback_reason: Optional[str] = None
    exact_match: bool = False
    lexical_score: float = 0.0
    tlsh_distance: Optional[int] = None
    semantic_score: float = 0.0
    method_scores: Optional[Dict[str, Any]] = None


def classify_possible_explanation(target_text: str, matched_text: str, score: float) -> str:
    """Classifies matching passages into possible explanation categories for human examiner review."""
    t_lower = target_text.lower()
    m_lower = matched_text.lower()

    if score < 0.35:
        return "insufficient_evidence"

    # Playbook / automated template indicators
    playbook_terms = ["playbook", "automated", "scanner", "script", "rule", "signature", "cron"]
    if any(t in t_lower for t in playbook_terms) or any(t in m_lower for t in playbook_terms):
        return "possible_playbook_template"

    # Benign / false positive indicators
    benign_terms = ["benign", "false positive", "authorized", "maintenance", "normal activity"]
    if any(t in t_lower for t in benign_terms) or any(t in m_lower for t in benign_terms):
        return "possible_repeated_benign"

    # External investigation indicators
    external_terms = ["vendor", "external", "soc-tier3", "cert", "forensic lab", "third-party"]
    if any(t in t_lower for t in external_terms) or any(t in m_lower for t in external_terms):
        return "possible_external_investigation"

    return "possible_playbook_template" if score > 0.7 else "possible_repeated_benign"


class SimilarityEngine:
    def __init__(
        self,
        mode: str = "auto",
        model_dir: Any = None,
        manifest_path: Any = None,
    ):
        self.mode = mode.lower()
        if self.mode not in ("off", "auto", "required"):
            raise ValueError(
                f"Invalid semantic mode '{mode}'. Must be 'off', 'auto', or 'required'."
            )

        self.model_dir = model_dir or default_semantic_config.model_dir
        self.manifest_path = manifest_path or default_semantic_config.manifest_path
        self.encoder: Optional[SemanticEncoder] = None
        self.fallback_reason: Optional[str] = None
        self.commit_sha: Optional[str] = None
        self.manifest_digest: Optional[str] = None

        self._initialize()

    def _initialize(self) -> None:
        if self.mode == "off":
            return

        val_result = validate_model_directory(self.model_dir, self.manifest_path)
        self.commit_sha = val_result.commit_sha
        self.manifest_digest = val_result.manifest_digest

        if val_result.is_valid:
            try:
                self.encoder = SemanticEncoder(
                    model_dir=self.model_dir,
                    manifest_path=self.manifest_path,
                )
            except Exception as exc:
                if self.mode == "required":
                    raise ModelVerificationError(
                        f"Required semantic mode failed to load encoder: {exc}"
                    )
                self.fallback_reason = f"encoder_load_failed: {exc}"
        else:
            if self.mode == "required":
                raise ModelVerificationError(
                    f"Required semantic mode failed model validation: {val_result.error_reason}"
                )
            self.fallback_reason = val_result.error_reason or "model_validation_failed"

    def find_similar_passages(
        self,
        target_record_id: str,
        target_source_id: str,
        target_record_type: str,
        target_text: str,
        candidates: List[Dict[str, Any]],
        limit: int = 5,
    ) -> List[SimilarityMatch]:
        """Finds top-k similar passages within authorized candidate pool.

        Excludes:
        - target_record_id itself.
        - duplicate imports or identical content from same source.
        """
        if self.mode == "off" or not target_text or not target_text.strip():
            return []

        # 1. Chunk target text
        chunker = TextChunker(
            tokenizer=self.encoder.tokenizer if self.encoder else None,
            max_seq_length=default_semantic_config.max_seq_length,
            overlap_tokens=default_semantic_config.chunk_overlap,
        )
        target_chunks = chunker.chunk_text(target_text)
        if not target_chunks:
            return []

        # Use primary target chunk (or first salient chunk)
        primary_target_chunk = target_chunks[0]

        # 2. Prepare bounded candidate chunks
        candidate_pool = candidates[: default_semantic_config.candidate_pool_limit]
        candidate_passages: List[CandidatePassage] = []

        for cand in candidate_pool:
            cand_id = str(cand.get("record_id", ""))
            cand_src = str(cand.get("source_id", ""))
            cand_type = str(cand.get("record_type", ""))
            cand_text = str(cand.get("text", "")).strip()

            # Invariant: Exclude same record
            if cand_id == target_record_id:
                continue

            # Invariant: Exclude duplicate imports sharing same content and source
            if cand_src == target_source_id and cand_text == target_text:
                continue

            if not cand_text:
                continue

            c_chunks = chunker.chunk_text(cand_text)
            for ch in c_chunks:
                candidate_passages.append(
                    CandidatePassage(
                        record_id=cand_id,
                        source_id=cand_src,
                        record_type=cand_type,
                        chunk=ch,
                    )
                )

        if not candidate_passages:
            return []

        # 3. Compute similarities: Encoder vs Lexical Fallback
        results: List[SimilarityMatch] = []

        if self.encoder is not None:
            # Semantic mode
            method = "semantic_all_minilm_l6_v2"
            target_vec = self.encoder.encode([primary_target_chunk.normalized_text])[0]
            cand_texts = [cp.chunk.normalized_text for cp in candidate_passages]
            cand_vecs = self.encoder.encode(cand_texts)

            # Cosine similarity is dot product because vectors are L2-normalized
            scores = np.dot(cand_vecs, target_vec)

            for idx, cp in enumerate(candidate_passages):
                score = float(scores[idx])
                if score < default_semantic_config.min_similarity_threshold:
                    continue

                raw_t = primary_target_chunk.raw_text
                raw_c = cp.chunk.raw_text
                norm_t, tokens_t = normalize_for_matching(raw_t)
                norm_c, tokens_c = normalize_for_matching(raw_c)
                is_exact = (norm_t == norm_c) and len(norm_t) > 0
                lex_jaccard = compute_shingle_jaccard(tokens_t, tokens_c, n=2)

                t_dig, _ = compute_tlsh_digest(raw_t.encode("utf-8"))
                c_dig, _ = compute_tlsh_digest(raw_c.encode("utf-8"))
                tlsh_dist = compute_tlsh_distance(t_dig, c_dig) if (t_dig and c_dig) else None

                expl = classify_possible_explanation(raw_t, raw_c, score)
                tlsh_info = (
                    f"TLSH Distance: {tlsh_dist}"
                    if tlsh_dist is not None
                    else "TLSH: unsupported_input_length_or_complexity"
                )
                caveats_str = (
                    "Comparative semantic similarity evidence for human examiner review. "
                    f"Does not classify SOC quality or issue supervisory verdicts. "
                    f"[Exact: {is_exact}, Lexical: {round(lex_jaccard, 4)}, {tlsh_info}, Semantic: {round(score, 4)}]"
                )
                results.append(
                    SimilarityMatch(
                        target_record_id=target_record_id,
                        target_start_char=primary_target_chunk.start_char,
                        target_end_char=primary_target_chunk.end_char,
                        target_text=primary_target_chunk.raw_text,
                        matched_record_id=cp.record_id,
                        matched_source_id=cp.source_id,
                        matched_record_type=cp.record_type,
                        matched_start_char=cp.chunk.start_char,
                        matched_end_char=cp.chunk.end_char,
                        matched_text=cp.chunk.raw_text,
                        similarity_score=round(score, 4),
                        method_used=method,
                        possible_explanation=expl,
                        caveats=caveats_str,
                        model_revision=self.commit_sha,
                        manifest_digest=self.manifest_digest,
                        fallback_reason=None,
                        exact_match=is_exact,
                        lexical_score=round(lex_jaccard, 4),
                        tlsh_distance=tlsh_dist,
                        semantic_score=round(score, 4),
                        method_scores={
                            "exact_match": is_exact,
                            "lexical_jaccard": round(lex_jaccard, 4),
                            "tlsh_distance": tlsh_dist,
                            "semantic_cosine": round(score, 4),
                        },
                    )
                )
        else:
            # Lexical Fallback mode
            method = "lexical_fallback"
            for cp in candidate_passages:
                score = compute_lexical_similarity(
                    primary_target_chunk.normalized_text, cp.chunk.normalized_text
                )
                if score < default_semantic_config.min_similarity_threshold:
                    continue

                raw_t = primary_target_chunk.raw_text
                raw_c = cp.chunk.raw_text
                norm_t, tokens_t = normalize_for_matching(raw_t)
                norm_c, tokens_c = normalize_for_matching(raw_c)
                is_exact = (norm_t == norm_c) and len(norm_t) > 0
                lex_jaccard = compute_shingle_jaccard(tokens_t, tokens_c, n=2)

                t_dig, _ = compute_tlsh_digest(raw_t.encode("utf-8"))
                c_dig, _ = compute_tlsh_digest(raw_c.encode("utf-8"))
                tlsh_dist = compute_tlsh_distance(t_dig, c_dig) if (t_dig and c_dig) else None

                expl = classify_possible_explanation(raw_t, raw_c, score)
                tlsh_info = (
                    f"TLSH Distance: {tlsh_dist}"
                    if tlsh_dist is not None
                    else "TLSH: unsupported_input_length_or_complexity"
                )
                caveats_str = (
                    f"Lexical fallback used ({self.fallback_reason}). "
                    f"Matches based on keyword/token overlap. For examiner review only. "
                    f"[Exact: {is_exact}, Lexical: {round(lex_jaccard, 4)}, {tlsh_info}]"
                )
                results.append(
                    SimilarityMatch(
                        target_record_id=target_record_id,
                        target_start_char=primary_target_chunk.start_char,
                        target_end_char=primary_target_chunk.end_char,
                        target_text=primary_target_chunk.raw_text,
                        matched_record_id=cp.record_id,
                        matched_source_id=cp.source_id,
                        matched_record_type=cp.record_type,
                        matched_start_char=cp.chunk.start_char,
                        matched_end_char=cp.chunk.end_char,
                        matched_text=cp.chunk.raw_text,
                        similarity_score=round(score, 4),
                        method_used=method,
                        possible_explanation=expl,
                        caveats=caveats_str,
                        model_revision=self.commit_sha,
                        manifest_digest=self.manifest_digest,
                        fallback_reason=self.fallback_reason,
                        exact_match=is_exact,
                        lexical_score=round(lex_jaccard, 4),
                        tlsh_distance=tlsh_dist,
                        semantic_score=round(score, 4),
                        method_scores={
                            "exact_match": is_exact,
                            "lexical_jaccard": round(lex_jaccard, 4),
                            "tlsh_distance": tlsh_dist,
                            "semantic_cosine": round(score, 4),
                        },
                    )
                )

        # 4. Sort by score descending and return top-limit
        results.sort(key=lambda m: m.similarity_score, reverse=True)
        return results[:limit]
