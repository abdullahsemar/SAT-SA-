# Hybrid Similarity Evaluation and Investigation Passage Matching

## 1. Executive Summary & Supervisory Context

SAT-SA evaluates textual similarities across historical investigation narratives, alert notes, and incident closure dispositions submitted by supervised entities.

> [!IMPORTANT]
> **Supervisory Meaning**: Similar wording across investigation records is a **non-adverse analytical observation** intended to assist human examiners in detecting repeated playbook patterns, recurring benign conditions, or potential investigation copy-pasting. It does **not** constitute proof of analyst fraud, negligence, or an operational control failure.

---

## 2. Four-Method Hybrid Similarity Architecture

SAT-SA decouples textual comparison into four complementary methods to avoid false positives and false negatives:

```
+---------------------------------------------------------------------------------------------------+
|                                 HYBRID SIMILARITY PIPELINE                                        |
+---------------------------------------------------------------------------------------------------+
|  Input Investigation Narrative                                                                    |
|        │                                                                                          |
|        ├─► [ 1. Exact Duplicate Match ] ────────────► Normalized byte string identity            |
|        │                                                                                          |
|        ├─► [ 2. Explainable Lexical Overlap ] ──────► 3-gram Word Shingle Jaccard Overlap        |
|        │                                                                                          |
|        ├─► [ 3. TLSH Fuzzy Hashing ] ───────────────► 128-bucket quartile distance (T1 format)   |
|        │                                              (Rejects <50 bytes / low entropy)           |
|        │                                                                                          |
|        └─► [ 4. Pretrained Semantic Encoder ] ──────► 384-dim dense embedding (all-MiniLM-L6-v2) |
|                                                       (Safetensors, offline inference)            |
+---------------------------------------------------------------------------------------------------+
```

### 2.1 Score Distinctions and Interpretability
SAT-SA strictly maintains distinct score scales and forbids naive unweighted averaging:
- **Exact Duplicate**: Boolean (`True` / `False`). Indicates identical normalized text.
- **Lexical Jaccard Score**: Ratio $[0.0, 1.0]$. Quantifies token/shingle overlap.
- **TLSH Distance**: Non-negative integer $\ge 0$.
  - $0$: Exact match.
  - $\le 30$: Very near duplicate (minor edits, variable changes).
  - $\le 100$: Moderately similar structural text.
  - $> 200$: Unrelated text.
  - *Note*: TLSH is **not** a percentage and lower numbers indicate higher similarity.
- **MiniLM Cosine Similarity**: Geometric vector alignment $[0.0, 1.0]$. Captures paraphrasing and conceptual synonymy.

---

## 3. Preservation of Negation and Operational State

In cybersecurity investigations, small linguistic differences completely invert meaning. SAT-SA's normalization pipeline explicitly preserves:
- **Negation words**: `not`, `no`, `never`, `without`.
- **Operational outcomes**: `failed`, `blocked`, `successful`, `permitted`, `quarantined`.
- **Chronology**: Timestamps, sequence references, and case identifiers.

### Example: Negation Differentiation
- Text A: *"Malicious payload execution was successful on internal workstation."*
- Text B: *"Malicious payload execution was blocked and failed on internal workstation."*
- **Result**: `exact_match=False`, lexical score reflects difference, semantic distance distinguishes disposition.

---

## 4. Short and Low-Complexity Input Handling (TLSH Invariant)

Per Trend Micro TLSH specifications, the algorithm is defined for text with sufficient length and entropy:
- **Minimum Length**: Inputs under 50 bytes cannot populate quartiles reliably and return `None` with reason `insufficient_input_length`.
- **Minimum Entropy**: Inputs with fewer than 10 unique byte values return `None` with reason `insufficient_entropy`.
- **Low Bucket Variance**: Inputs with fewer than 32 non-zero buckets return `None` with reason `insufficient_complexity`.

SAT-SA **never** artificially pads short strings to force a fuzzy digest. When TLSH is inapplicable, lexical and semantic methods handle the comparison seamlessly.

---

## 5. Pretrained Model Invariants (Offline Sentence-Transformers)

1. **Model Specification**: `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions).
2. **Local Weights Storage**: Loaded strictly from local safetensors (`models/all-MiniLM-L6-v2/`).
3. **Air-Gapped Operation**: `local_files_only=True` is enforced; network calls to HuggingFace or remote endpoints are prohibited.
4. **Execution Modes**:
   - `off`: Disables dense embeddings; uses lexical/fuzzy matching only.
   - `auto`: Uses semantic embeddings if weights are present; falls back gracefully if unavailable.
   - `required`: Fails fast if model weights are missing or corrupt.

---

## 6. Exact Source Character Span Invariant

Every match displayed in the examiner UI satisfies the cryptographic span invariant:
$$\text{source\_text}[\text{start\_char} : \text{end\_char}] == \text{matched\_text}$$
This guarantees that examiners are never misled by truncated or hallucinated text snippets.

---

## 7. Synthetic Evaluation Fixture Benchmarks

| Fixture Category | Example Scenario | Exact Match | Lexical Jaccard | TLSH Distance | MiniLM Cosine |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Exact Copy** | Repeated closure notes across alerts | `True` | 1.00 | 0 | 1.00 |
| **Identifier Change** | IP/Host change in identical narrative | `False` | 0.88 | 18 | 0.96 |
| **Minor Edit** | Wording typo or timestamp tweak | `False` | 0.82 | 24 | 0.94 |
| **Playbook Template** | Standard phishing checklist boilerplate | `False` | 0.74 | 36 | 0.91 |
| **Paraphrase** | Same meaning, different vocabulary | `False` | 0.28 | N/A (>150) | 0.86 |
| **Negation Inversion** | *"blocked"* vs *"successful"* | `False` | 0.72 | 48 | 0.79 |
| **Short Note (<50b)** | *"Closed as false positive"* | `False` | 1.00 | N/A (too short) | 1.00 |
| **Unrelated Narrative** | Firewall maintenance vs ransomware | `False` | 0.05 | > 220 | 0.18 |
