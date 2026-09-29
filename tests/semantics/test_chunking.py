"""Tests for token-bounded chunking and exact character span preservation."""

from __future__ import annotations

from packages.analytics.semantics.chunking import TextChunker, normalize_investigation_text
from packages.analytics.semantics.config import default_semantic_config
from packages.analytics.semantics.encoder import SemanticEncoder


def test_empty_and_whitespace_input_produces_empty_chunks():
    """Empty or whitespace-only input yields no chunks."""
    chunker = TextChunker(max_seq_length=256, overlap_tokens=32)
    assert chunker.chunk_text("") == []
    assert chunker.chunk_text("   \n\t  ") == []


def test_short_narrative_single_chunk():
    """Short note fits in single chunk with exact span match."""
    chunker = TextChunker(max_seq_length=256, overlap_tokens=32)
    text = "Analyst verified source IP 192.168.1.50 belongs to internal vulnerability scanner."
    chunks = chunker.chunk_text(text)

    assert len(chunks) == 1
    ch = chunks[0]
    assert ch.start_char == 0
    assert ch.end_char == len(text)
    assert text[ch.start_char : ch.end_char] == text
    assert ch.raw_text == text
    assert len(ch.chunk_hash) == 64


def test_long_narrative_multi_chunk_complete_coverage():
    """Narrative exceeding 256 tokens is covered to its ending without silent truncation."""
    # Generate a narrative > 300 words
    sentences = [
        f"Step {i}: Forensic analysis of memory dump for host workstation-{i:03d} completed."
        for i in range(1, 50)
    ]
    long_narrative = " ".join(sentences)
    assert len(long_narrative.split()) > 350

    # Test with real tokenizer from provisioned model
    encoder = SemanticEncoder()
    chunker = TextChunker(
        tokenizer=encoder.tokenizer,
        max_seq_length=default_semantic_config.max_seq_length,
        overlap_tokens=default_semantic_config.chunk_overlap,
    )
    chunks = chunker.chunk_text(long_narrative)

    assert len(chunks) > 1, "Long text should produce multiple chunks"

    # Invariant 1: exact character spans
    for ch in chunks:
        assert long_narrative[ch.start_char : ch.end_char] == ch.raw_text
        assert ch.token_count <= chunker.max_tokens

    # Invariant 2: narrative tail is covered to the very end
    last_chunk = chunks[-1]
    assert last_chunk.end_char == len(long_narrative)
    assert "Step 49:" in last_chunk.raw_text


def test_text_normalization_strips_headers():
    """Boilerplate headers like [TRIAGE NOTE] are stripped in normalized text."""
    raw = "[TRIAGE NOTE] Verified alert is benign scanner activity."
    norm = normalize_investigation_text(raw)
    assert norm == "verified alert is benign scanner activity."
    assert not norm.startswith("[triage")
