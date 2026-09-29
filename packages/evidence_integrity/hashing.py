"""Cryptographic hashing primitives, exact-byte digests, and domain-separated Merkle trees.

Invariants:
- Raw-file SHA-256 is strictly computed over exact submitted bytes.
- Never conflates raw file hashes with canonical record commitments, fuzzy hashes, or embeddings.
- Merkle tree uses domain separation per RFC 6962:
  - Leaf prefix: 0x00
  - Internal node prefix: 0x01
- Inclusion proofs provide cryptographic auditability of batch membership.
- Cryptographically secure per-record nonces resist dictionary attacks.
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


def hash_raw_bytes(data: bytes) -> str:
    """Computes exact SHA-256 hex digest of raw submitted bytes."""
    return hashlib.sha256(data).hexdigest()


hash_bytes = hash_raw_bytes


def hash_file_path(path: Union[str, Path], chunk_size: int = 65536) -> str:
    """Computes exact SHA-256 hex digest of a file on disk via streaming."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


hash_file = hash_file_path


def generate_record_nonce() -> str:
    """Generates a 128-bit cryptographically secure per-record salt/nonce."""
    return secrets.token_hex(16)


def _hash_leaf(leaf_bytes: bytes) -> bytes:
    """RFC 6962 domain-separated leaf hash: SHA256(0x00 || leaf_data)."""
    return hashlib.sha256(b"\x00" + leaf_bytes).digest()


def _hash_internal(left_bytes: bytes, right_bytes: bytes) -> bytes:
    """RFC 6962 domain-separated internal node hash: SHA256(0x01 || left || right)."""
    return hashlib.sha256(b"\x01" + left_bytes + right_bytes).digest()


class MerkleTree:
    """Deterministic domain-separated Merkle Tree for evidence batches."""

    def __init__(self, leaf_items: Optional[List[Union[str, bytes]]] = None):
        """Initializes Merkle Tree with leaf commitments or raw byte items."""
        self.leaves: List[bytes] = []
        if leaf_items:
            for item in leaf_items:
                if isinstance(item, str):
                    self.leaves.append(item.encode("utf-8"))
                else:
                    self.leaves.append(item)

        self._leaf_hashes: List[bytes] = [_hash_leaf(leaf) for leaf in self.leaves]
        self._tree_size: int = len(self.leaves)

    @property
    def tree_size(self) -> int:
        return self._tree_size

    @property
    def leaf_count(self) -> int:
        return self._tree_size

    @property
    def root(self) -> str:
        return self.get_root_hex()

    def get_root_bytes(self) -> bytes:
        """Returns the Merkle Tree root as 32 raw bytes."""
        if not self._leaf_hashes:
            return hashlib.sha256(b"").digest()
        return self._compute_subtree_root(0, self._tree_size)

    def get_root_hex(self) -> str:
        """Returns the Merkle Tree root as 64-character lowercase hex string."""
        return self.get_root_bytes().hex()

    def _compute_subtree_root(self, start: int, end: int) -> bytes:
        """Computes subtree root using RFC 6962 binary subdivision."""
        count = end - start
        if count == 1:
            return self._leaf_hashes[start]

        # Largest power of 2 less than count
        k = 1 << ((count - 1).bit_length() - 1)
        left = self._compute_subtree_root(start, start + k)
        right = self._compute_subtree_root(start + k, end)
        return _hash_internal(left, right)

    def get_inclusion_proof(self, index: int) -> List[Dict[str, str]]:
        """Generates an audit path / inclusion proof for leaf at `index`.

        Returns list of proof steps: [{"direction": "left"|"right", "hash": "<hex>"}]
        """
        if index < 0 or index >= self._tree_size:
            raise IndexError(f"Leaf index {index} out of bounds for tree size {self._tree_size}")

        proof: List[Dict[str, str]] = []
        self._build_proof(0, self._tree_size, index, proof)
        return proof

    def _build_proof(self, start: int, end: int, index: int, proof: List[Dict[str, str]]) -> None:
        count = end - start
        if count <= 1:
            return

        k = 1 << ((count - 1).bit_length() - 1)
        split = start + k

        if index < split:
            # Target is in left subtree, sibling is right subtree root
            sibling = self._compute_subtree_root(split, end)
            proof.append({"direction": "right", "hash": sibling.hex()})
            self._build_proof(start, split, index, proof)
        else:
            # Target is in right subtree, sibling is left subtree root
            sibling = self._compute_subtree_root(start, split)
            proof.append({"direction": "left", "hash": sibling.hex()})
            self._build_proof(split, end, index, proof)


def _compute_audit_path_directions(index: int, tree_size: int) -> List[str]:
    directions = []
    start, end = 0, tree_size
    while end - start > 1:
        count = end - start
        k = 1 << ((count - 1).bit_length() - 1)
        split = start + k
        if index < split:
            directions.append("right")
            end = split
        else:
            directions.append("left")
            start = split
    return directions


def verify_inclusion_proof(
    leaf_item: Union[str, bytes],
    index: int,
    tree_size: int,
    proof: List[Any],
    expected_root_hex: str,
) -> bool:
    """Verifies that `leaf_item` at `index` is included in the Merkle Tree with `expected_root_hex`."""
    if index < 0 or index >= tree_size:
        return False

    expected_directions = _compute_audit_path_directions(index, tree_size)
    if len(proof) != len(expected_directions):
        return False

    leaf_bytes = leaf_item.encode("utf-8") if isinstance(leaf_item, str) else leaf_item
    current = _hash_leaf(leaf_bytes)

    # In RFC 6962 proof path, the proof elements are traversed from bottom to top
    # The proof was collected top-down in `_build_proof`, so reverse it for bottom-up verification
    rev_directions = list(reversed(expected_directions))
    for i, step in enumerate(reversed(proof)):
        expected_dir = rev_directions[i]
        if isinstance(step, (tuple, list)):
            direction = "left" if step[0] in ("left", "L") else "right"
            sibling = bytes.fromhex(step[1])
        elif isinstance(step, dict):
            direction = step.get("direction")
            sibling = bytes.fromhex(step["hash"])
        else:
            return False

        if direction != expected_dir:
            return False

        if direction == "left":
            current = _hash_internal(sibling, current)
        elif direction == "right":
            current = _hash_internal(current, sibling)
        else:
            return False

    return current.hex().lower() == expected_root_hex.lower()


verify_merkle_inclusion_proof = verify_inclusion_proof
