"""Standard Ed25519 digital signature scheme and key lifecycle management.

Preserves core trust boundaries:
- Uses maintained 'cryptography' library primitives (never custom cryptographic primitives).
- Service keys attest strictly to what the application service recorded; they are NOT personal examiner signatures.
- Examiner keys attest to human determinations and supervisory deliberations.
- Keys are identified by distinct 'key_id'.
- Public keys and checkpoints must be provisioned independently of the artifact being verified.
"""

from __future__ import annotations

import base64
import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def generate_ed25519_keypair() -> Tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    """Generates a fresh Ed25519 private/public keypair."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def export_public_key_b64(public_key: ed25519.Ed25519PublicKey) -> str:
    """Exports an Ed25519 public key as raw 32-byte Base64 string."""
    raw_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw_bytes).decode("ascii")


def load_public_key_b64(b64_str: str) -> ed25519.Ed25519PublicKey:
    """Loads an Ed25519 public key from a 32-byte Base64 string."""
    raw_bytes = base64.b64decode(b64_str.strip())
    if len(raw_bytes) != 32:
        raise ValueError(f"Invalid Ed25519 public key byte length: {len(raw_bytes)} (expected 32)")
    return ed25519.Ed25519PublicKey.from_public_bytes(raw_bytes)


def export_private_key_pem(private_key: ed25519.Ed25519PrivateKey) -> str:
    """Exports an Ed25519 private key in PKCS#8 PEM format without password."""
    pem_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem_bytes.decode("utf-8")


def load_private_key_pem(pem_str: str) -> ed25519.Ed25519PrivateKey:
    """Loads an Ed25519 private key from PKCS#8 PEM format."""
    return serialization.load_pem_private_key(pem_str.encode("utf-8"), password=None)  # type: ignore


def export_private_key_b64(private_key: ed25519.Ed25519PrivateKey) -> str:
    """Exports an Ed25519 private key as raw 32-byte Base64 string."""
    raw_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(raw_bytes).decode("ascii")


def load_private_key_b64(b64_str: str) -> ed25519.Ed25519PrivateKey:
    """Loads an Ed25519 private key from a 32-byte Base64 string."""
    raw_bytes = base64.b64decode(b64_str.strip())
    if len(raw_bytes) != 32:
        raise ValueError(f"Invalid Ed25519 private key byte length: {len(raw_bytes)} (expected 32)")
    return ed25519.Ed25519PrivateKey.from_private_bytes(raw_bytes)


def sign_data(private_key: ed25519.Ed25519PrivateKey, data: bytes) -> str:
    """Signs bytes with Ed25519 and returns Base64 encoded signature."""
    signature = private_key.sign(data)
    return base64.b64encode(signature).decode("ascii")


def verify_signature(public_key: ed25519.Ed25519PublicKey, data: bytes, signature_b64: str) -> bool:
    """Verifies Base64 encoded Ed25519 signature over data bytes."""
    try:
        sig_bytes = base64.b64decode(signature_b64.strip())
        public_key.verify(sig_bytes, data)
        return True
    except (InvalidSignature, ValueError, Exception):
        return False


class KeyRegistry:
    """Manages active, rotated, and historical verification public keys."""

    def __init__(self, keys_dir: Optional[Path] = None):
        self.keys_dir = keys_dir or (
            Path(__file__).resolve().parent.parent.parent / "config" / "keys"
        )
        self.trusted_keys: Dict[str, Dict[str, Any]] = {}
        self._service_private_key: Optional[ed25519.Ed25519PrivateKey] = None
        self._service_key_id: str = "sat-sa-service-audit-v1"
        self._initialize()

    def _initialize(self) -> None:
        """Loads trusted public keys and provisions local service key if not present."""
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        priv_path = self.keys_dir / "service_audit_private.pem"
        pub_path = self.keys_dir / "service_audit_public.b64"

        if priv_path.exists() and pub_path.exists():
            with open(priv_path, "r", encoding="utf-8") as f:
                self._service_private_key = load_private_key_pem(f.read())
            with open(pub_path, "r", encoding="utf-8") as f:
                pub_b64 = f.read().strip()
        else:
            # Generate deterministic or initial key for local deployment
            priv, pub = generate_ed25519_keypair()
            self._service_private_key = priv
            pub_b64 = export_public_key_b64(pub)
            with open(priv_path, "w", encoding="utf-8") as f:
                f.write(export_private_key_pem(priv))
            with open(pub_path, "w", encoding="utf-8") as f:
                f.write(pub_b64)

        self.trusted_keys[self._service_key_id] = {
            "key_id": self._service_key_id,
            "role": "service_audit",
            "public_key_b64": pub_b64,
            "status": "active",
            "valid_from": "2026-01-01T00:00:00Z",
        }

    def get_service_signer(self) -> Tuple[str, ed25519.Ed25519PrivateKey]:
        """Returns the active service key ID and private key for system audit signing."""
        if not self._service_private_key:
            raise RuntimeError("Service signing key is not initialized.")
        return self._service_key_id, self._service_private_key

    def get_public_key(self, key_id: str) -> Optional[ed25519.Ed25519PublicKey]:
        """Resolves public key object for key_id."""
        info = self.trusted_keys.get(key_id)
        if not info or info.get("status") == "revoked":
            return None
        return load_public_key_b64(info["public_key_b64"])

    def register_key(
        self,
        key_id: str,
        public_key_b64: str,
        role: str = "service_audit",
        status: str = "active",
        valid_from: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Registers a trusted public key."""
        # Validate format
        load_public_key_b64(public_key_b64)
        self.trusted_keys[key_id] = {
            "key_id": key_id,
            "role": role,
            "public_key_b64": public_key_b64,
            "status": status,
            "valid_from": valid_from or datetime.datetime.now(datetime.timezone.utc).isoformat(),
            **kwargs,
        }

    def verify(self, key_id: str, data: bytes, signature_b64: str) -> bool:
        """Verifies a signature against the registered public key for key_id."""
        pub = self.get_public_key(key_id)
        if not pub:
            return False
        return verify_signature(pub, data, signature_b64)


# Singleton key registry
default_key_registry = KeyRegistry()
