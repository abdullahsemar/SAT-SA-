"""Pretrained Transformer Encoder for investigation passages in SAT-SA.

Loads sentence-transformers/all-MiniLM-L6-v2 offline with:
- trust_remote_code=False
- local_files_only=True
- use_safetensors=True
- Attention-mask-aware mean pooling and L2 normalization
- 384-dimensional unit vector outputs
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Union

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from packages.analytics.semantics.config import default_semantic_config
from packages.analytics.semantics.registry import (
    ModelVerificationError,
    validate_model_directory,
)


class SemanticEncoder:
    def __init__(
        self,
        model_dir: Path | str | None = None,
        manifest_path: Path | str | None = None,
        max_seq_length: int = 256,
    ):
        self.model_dir = Path(model_dir or default_semantic_config.model_dir).resolve()
        self.manifest_path = Path(manifest_path or default_semantic_config.manifest_path).resolve()
        self.max_seq_length = max_seq_length

        # 1. Validate security & hashes before loading
        val_result = validate_model_directory(self.model_dir, self.manifest_path)
        if not val_result.is_valid:
            raise ModelVerificationError(f"Model validation failed: {val_result.error_reason}")

        self.commit_sha = val_result.commit_sha
        self.manifest_digest = val_result.manifest_digest

        # 2. Load tokenizer and model offline
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(self.model_dir),
            local_files_only=True,
        )
        self.model = AutoModel.from_pretrained(
            str(self.model_dir),
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
        )
        self.model.eval()

    def encode(
        self,
        texts: Union[str, List[str]],
        batch_size: int = 32,
    ) -> np.ndarray:
        """Encodes texts into L2-normalized 384-dimensional embeddings."""
        if isinstance(texts, str):
            texts = [texts]

        if not texts:
            return np.zeros((0, 384), dtype=np.float32)

        # Filter and track non-empty texts
        all_embeddings: List[np.ndarray] = []

        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            # Replace empty strings with a blank placeholder to preserve index
            safe_batch = [t if t and t.strip() else " " for t in batch_texts]

            encoded_input = self.tokenizer(
                safe_batch,
                padding=True,
                truncation=True,
                max_length=self.max_seq_length,
                return_tensors="pt",
            )

            with torch.no_grad():
                model_output = self.model(**encoded_input)
                token_embeddings = model_output[0]  # First element is last_hidden_state
                attention_mask = encoded_input["attention_mask"]

                # Attention-mask-aware mean pooling
                input_mask_expanded = (
                    attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
                )
                sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
                sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
                mean_pooled = sum_embeddings / sum_mask

                # L2 Normalization
                normalized = torch.nn.functional.normalize(mean_pooled, p=2, dim=1)
                batch_vectors = normalized.cpu().numpy().astype(np.float32)

                # Zero out embeddings for texts that were originally empty
                for idx, orig in enumerate(batch_texts):
                    if not orig or not orig.strip():
                        batch_vectors[idx] = 0.0

                all_embeddings.append(batch_vectors)

        return np.vstack(all_embeddings) if all_embeddings else np.zeros((0, 384), dtype=np.float32)
