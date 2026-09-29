# Model Card: sentence-transformers/all-MiniLM-L6-v2 (SAT-SA Task 3)

## 1. Model Details

- **Model Name**: `sentence-transformers/all-MiniLM-L6-v2`
- **Publisher**: Sentence Transformers (`sentence-transformers` on Hugging Face Hub)
- **Pinned Revision (Commit SHA)**: `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`
- **License**: Apache-2.0 (per repository declaration and release metadata)
- **Base Architecture**: `BertModel` (`nreimers/MiniLM-L6-H384-uncased`)
  - 6 Transformer encoder layers
  - 384 hidden dimension
  - 12 attention heads
  - 22,713,216 parameters (~22.7M parameters)
- **Framework & Format**: PyTorch / Hugging Face Transformers loaded via `.safetensors`
- **Storage Size**: 90.87 MB (`model.safetensors`) + 700 KB tokenizer/configs

## 2. Intended Purpose & Trust Boundaries

- **Intended Use**: Comparative passage similarity retrieval to provide human supervisory examiners with historical context (e.g., recurring investigation dispositions, playbook templates, or repeated benign notes) during SOC assessments.
- **Out-of-Scope & Prohibited Uses**:
  - The model **does NOT** classify SOC operational quality.
  - The model **does NOT** assess whether an investigation occurred.
  - The model **does NOT** issue autonomous regulatory pass/fail sanctions or supervisory verdicts.
- **Language Scope**: English (`en`). Evaluated prototype language is strictly English investigative notes and incident response narratives. Non-English texts are unvalidated and may produce distorted or degraded similarity scores.

## 3. Architecture, Preprocessing & Pooling

- **Tokenization**: WordPiece tokenizer (`AutoTokenizer`) with lowercase uncased normalization.
- **Sequence Length**: Max 256 tokens total (reserves 2 tokens for `[CLS]` and `[SEP]`, leaving 254 effective text tokens per window).
- **Chunking Strategy**: Token-bounded overlapping windows (window size: 254, overlap: 32 tokens).
  - Exact character span preservation: `text[start_char:end_char] == chunk_raw_text`.
  - Complete narrative coverage: notes exceeding 256 word pieces are chunked across multiple windows through to their final character without silent truncation.
- **Pooling & Normalization**:
  - Attention-mask-aware mean pooling:
    $$\mathbf{u} = \frac{\sum_{i=1}^{L} \mathbf{h}_i \cdot m_i}{\max\left(\sum_{i=1}^{L} m_i, 10^{-9}\right)}$$
    Where $\mathbf{h}_i$ is the last hidden state of token $i$, and $m_i \in \{0, 1\}$ is the attention mask.
  - L2 Normalization:
    $$\mathbf{e} = \frac{\mathbf{u}}{\|\mathbf{u}\|_2}$$
  - Similarity Metric: Cosine similarity $\mathbf{e}_1 \cdot \mathbf{e}_2 \in [-1.0, 1.0]$ bounded in $[0.0, 1.0]$.

## 4. Cryptographic File Inventory & Hashes

The model files are verified at runtime against `models/manifest.json`:

| File Relative Path | Size (Bytes) | File Type | SHA-256 Hash |
|---|---|---|---|
| `config.json` | 612 | `json` | `953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41` |
| `model.safetensors` | 90,868,376 | `safetensors` | `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db` |
| `tokenizer.json` | 466,247 | `json` | `be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037` |
| `tokenizer_config.json` | 350 | `json` | `acb92769e8195aabd29b7b2137a9e6d6e25c476a4f15aa4355c233426c61576b` |
| `vocab.txt` | 231,508 | `text` | `07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3` |
| `special_tokens_map.json` | 112 | `json` | `303df45a03609e4ead04bc3dc1536d0ab19b5358db685b6f3da123d05ec200e3` |
| `1_Pooling/config.json` | 190 | `json` | `4be450dde3b0273bb9787637cfbd28fe04a7ba6ab9d36ac48e92b11e350ffc23` |

## 5. Security & Trust Boundaries

- **Separation of Modes**:
  - **Provisioning**: Executed exclusively on an internet-connected dev machine via `scripts/provision_model.py`. Checks publisher commit existence, downloads allowlisted `.safetensors` and JSON/vocab files, and computes SHA-256 hashes. Rejects all `.bin`, `.pt`, `.pkl`, `.py`, `.sh`, and custom code.
  - **Runtime**: Operates strictly offline. Enforces `HF_HUB_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, `TRANSFORMERS_OFFLINE=1`. Uses `local_files_only=True`, `trust_remote_code=False`, and `use_safetensors=True`. Rejects path escapes and symlinks.
- **Manifest Integrity**: Hashes verify integrity and consistency with the release manifest; they do not serve as an independent guarantee of library harmlessness.
- **Fail-Safe Fallback**: If weights are missing or altered:
  - In `auto` mode: activates transparent, labeled lexical fallback (`method="lexical_fallback"`).
  - In `required` mode: halts assessment with clear verification failure (`ModelVerificationError`); never silently falls back or exposes partial results.
- **Read-Only Inspection**: `GET /api/v1/findings/{id}/similar-passages` is strictly read-only. It queries previously persisted results from the run transaction and never invokes the encoder or updates analytical state on GET.

## 6. Hardware & Measured Local Test Timings

- **Evaluation Environment**: Windows x86_64, Python 3.14.6 / PyTorch 2.14.0 CPU
- **Local Model Load Time**: ~0.45s (offline from SSD)
- **Inference Latency (Single Passage)**: ~52ms
- **Batch Throughput (CPU)**: 10 passages in 0.487s (~48.7ms / passage)
- **Memory Footprint**: ~160 MB RSS during active CPU batch inference

## 7. Retrieval Limitations & Risk Disclosures

1. **Negation Sensitivity**: Pretrained sentence encoders are semantic embedding models, not logical reasoning engines. Negations (e.g. *"Hostile actor detected"* vs *"No hostile actor detected"*) share high vocabulary overlap and may produce moderate similarity scores. Examiners are alerted via explicit caveats.
2. **Boilerplate Matching**: Standard playbook actions and scanner templates will exhibit high similarity ($> 0.80$). These are classified as *possible playbook templates* for human examiner evaluation, not proof of superficial handling.
3. **Lexical Fallback Differences**: Lexical fallback matches by term frequency overlap (BM25/token Jaccard). It lacks semantic synonymy (e.g., *"originating"* vs *"source"*), but maintains deterministic provenance and explainability.

## 8. Controlled Update & Rollback Procedures

- **Updates**: Upgrading the model requires executing `scripts/provision_model.py` with a new validated commit SHA, generating a new `models/manifest.json`, running the full test regression suite, and generating a new model card revision.
- **Historical Immutability**: Updating the local model weights never mutates historical `analysis_runs` or `finding_similar_passages` tables. Completed historical runs remain permanently bound to their recorded `model_revision` and `manifest_digest`.
- **Rollback**: To roll back to a previous manifest, restore `models/manifest.json` and the corresponding files from version control and re-run verification tests.

## 9. Citations & References

- Sentence-Transformers Model Card: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- Hugging Face Transformers Offline Mode: https://huggingface.co/docs/transformers/installation#offline-mode
- Hugging Face Pickle Security: https://huggingface.co/docs/hub/security-pickle
- Hugging Face Transformers Security Policy: https://github.com/huggingface/transformers/security/policy
- Hugging Face Hub Environment Variables: https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables

---

## 10. Hybrid Near-Duplicate Architecture & Multi-Channel Matching

As implemented in Prompt 1, SAT-SA combines semantic embeddings with deterministic lexical and fuzzy representations:

### 10.1 Multi-Channel Decomposition

1. **Exact Duplicate Channel**: Versioned text normalization strictly preserving negation (`not`, `failed`, `blocked`, `successful`, `denied`). Generates exact character span matches.
2. **Explainable Lexical Shingling**: Word 2-shingle Jaccard overlap ($J \in [0.0, 1.0]$) providing human-interpretable measures of phrase re-use.
3. **Fuzzy Hashing Channel (TLSH)**: Locality Sensitive Hashing per Trend Micro reference specification (Oliver, Cheng, Chen 2013). Produces 70-character hex digests (`T1` prefix, 128 bucket counts, quartile ratio encoding).
   - **Input Complexity Gate**: Strictly enforces minimum 50 bytes and entropy thresholds. Short notes or low-complexity strings return explicit `insufficient_complexity` reasons and are never artificially padded.
   - **Distance Interpretation**: Distance metric $D \in [0, 300+]$ where $D < 30$ represents near-identical phrasing and $D < 100$ represents strong structural similarity.
4. **Semantic Embedding Channel (MiniLM-L6-v2)**: 384-dimensional cosine similarity ($\cos(\theta) \in [0.0, 1.0]$) capturing conceptual synonymy and paraphrasing.

### 10.2 Mathematical Independence of Metrics

Scores across channels are **never averaged or conflated**:
- TLSH distance is a distance metric, not a similarity probability.
- Jaccard overlap is a lexical token set intersection.
- Cosine similarity is an angular vector displacement.
Each metric is persisted with its independent algorithm version, threshold parameters, and exact character offsets.

### 10.3 Supervisory Examination Policy

Similar investigative wording is a **non-adverse contextual observation** for human examiner review. It does not constitute proof of falsified triage, automated copy-pasting, or operational deficiency. Examiners review candidate passages in the context of standard operating procedures, vendor playbooks, and benign recurrence.
