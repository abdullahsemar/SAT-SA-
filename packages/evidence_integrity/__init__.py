"""Cryptographic evidence integrity, canonical serialization, custody logging, and ledger anchoring."""

from packages.evidence_integrity.canonical import (
    build_record_commitment,
    canonical_json_dumps,
    compute_canonical_digest,
    normalize_value,
)
from packages.evidence_integrity.custody import CustodyLogManager
from packages.evidence_integrity.fabric_client import FabricGatewayClient, default_fabric_client
from packages.evidence_integrity.hashing import (
    MerkleTree,
    generate_record_nonce,
    hash_file_path,
    hash_raw_bytes,
    verify_inclusion_proof,
)
from packages.evidence_integrity.outbox import OutboxProcessor
from packages.evidence_integrity.signatures import (
    KeyRegistry,
    default_key_registry,
    generate_ed25519_keypair,
    sign_data,
    verify_signature,
)
from packages.evidence_integrity.verifier import (
    EvidenceVerifier,
    StandaloneEvidenceVerifier,
    VerificationResult,
)

__all__ = [
    "normalize_value",
    "canonical_json_dumps",
    "compute_canonical_digest",
    "build_record_commitment",
    "hash_raw_bytes",
    "hash_file_path",
    "generate_record_nonce",
    "MerkleTree",
    "verify_inclusion_proof",
    "generate_ed25519_keypair",
    "sign_data",
    "verify_signature",
    "KeyRegistry",
    "default_key_registry",
    "CustodyLogManager",
    "FabricGatewayClient",
    "default_fabric_client",
    "OutboxProcessor",
    "EvidenceVerifier",
    "StandaloneEvidenceVerifier",
    "VerificationResult",
]
