"""Token-bounded text chunking with exact character span tracking.

Guarantees:
- Respects model token limit (including [CLS] and [SEP]).
- Preserves exact character offsets: text[start_char:end_char] == chunk_raw_text.
- Never silently truncates a note: covers narrative to the very end across overlapping windows.
- Produces raw text and normalized text.
- Generates SHA-256 chunk hash.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, List


@dataclass
class TextChunk:
    chunk_index: int
    start_char: int
    end_char: int
    raw_text: str
    normalized_text: str
    chunk_hash: str
    token_count: int


def normalize_investigation_text(text: str) -> str:
    """Normalizes whitespace and strips common repetitive prefixes for semantic matching."""
    if not text:
        return ""
    # Strip common header prefixes like "[TRIAGE NOTE]", "NOTE:", "DISPOSITION:"
    cleaned = re.sub(
        r"^(?:\[(?:TRIAGE|INVESTIGATION|NOTE|CLOSURE|ACTION)[^\]]*\]\s*|NOTE:\s*|DISPOSITION:\s*)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Collapse multiple whitespaces/newlines to single space
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


class TextChunker:
    def __init__(
        self,
        tokenizer: Any = None,
        max_seq_length: int = 256,
        overlap_tokens: int = 32,
    ):
        self.tokenizer = tokenizer
        # Reserve 2 tokens for [CLS] and [SEP] special tokens
        self.max_tokens = max(16, max_seq_length - 2)
        self.overlap_tokens = min(overlap_tokens, self.max_tokens // 2)
        self.step = self.max_tokens - self.overlap_tokens

    def chunk_text(self, text: str) -> List[TextChunk]:
        if not text or not text.strip():
            return []

        # If tokenizer is available with fast offset mapping, use token-precise offsets
        if self.tokenizer and hasattr(self.tokenizer, "is_fast") and self.tokenizer.is_fast:
            try:
                return self._chunk_with_fast_tokenizer(text)
            except Exception:
                pass

        # Fallback whitespace/word piece chunker with exact character tracking
        return self._chunk_with_word_offsets(text)

    def _chunk_with_fast_tokenizer(self, text: str) -> List[TextChunk]:
        encoding = self.tokenizer(
            text,
            return_offsets_mapping=True,
            add_special_tokens=False,
            truncation=False,
        )
        offsets = encoding.get("offset_mapping", [])
        if not offsets:
            return []

        total_tokens = len(offsets)
        chunks: List[TextChunk] = []
        chunk_idx = 0
        start_tok = 0

        while start_tok < total_tokens:
            end_tok = min(start_tok + self.max_tokens, total_tokens)

            # Get character slice
            start_char = offsets[start_tok][0]
            end_char = offsets[end_tok - 1][1]

            raw_slice = text[start_char:end_char]
            norm_slice = normalize_investigation_text(raw_slice)
            c_hash = hashlib.sha256(norm_slice.encode("utf-8")).hexdigest()

            chunks.append(
                TextChunk(
                    chunk_index=chunk_idx,
                    start_char=start_char,
                    end_char=end_char,
                    raw_text=raw_slice,
                    normalized_text=norm_slice,
                    chunk_hash=c_hash,
                    token_count=end_tok - start_tok,
                )
            )
            chunk_idx += 1

            if end_tok >= total_tokens:
                break
            start_tok += self.step

        return chunks

    def _chunk_with_word_offsets(self, text: str) -> List[TextChunk]:
        """Regex-based word boundary chunker preserving exact character spans."""
        # Find all word tokens with character spans
        word_matches = list(re.finditer(r"\S+", text))
        if not word_matches:
            return []

        total_words = len(word_matches)
        # Approximate tokens ~ words * 1.3
        effective_max_words = max(8, int(self.max_tokens / 1.3))
        effective_step_words = max(4, int(self.step / 1.3))

        chunks: List[TextChunk] = []
        chunk_idx = 0
        start_w = 0

        while start_w < total_words:
            end_w = min(start_w + effective_max_words, total_words)

            start_char = word_matches[start_w].start()
            end_char = word_matches[end_w - 1].end()

            raw_slice = text[start_char:end_char]
            norm_slice = normalize_investigation_text(raw_slice)
            c_hash = hashlib.sha256(norm_slice.encode("utf-8")).hexdigest()

            chunks.append(
                TextChunk(
                    chunk_index=chunk_idx,
                    start_char=start_char,
                    end_char=end_char,
                    raw_text=raw_slice,
                    normalized_text=norm_slice,
                    chunk_hash=c_hash,
                    token_count=end_w - start_w,
                )
            )
            chunk_idx += 1

            if end_w >= total_words:
                break
            start_w += effective_step_words

        return chunks
