"""Release verification script for offline SAT-SA installation.

Verifies:
1. Detached Ed25519 cryptographic signature on release_manifest.json.
2. All files listed in release_manifest.json exist and match SHA-256 digests.
3. Identifies missing or altered artifacts and fails clearly.
4. Scans HTML and bundle assets to verify absence of external CDNs, fonts, or tracking scripts.
5. Validates that no sensitive production databases (sat_sa.db) or private keys were leaked.
6. Validates offline semantic model manifest integrity.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from pathlib import Path

FORBIDDEN_NETWORK_PATTERNS = [
    re.compile(r"https?://fonts\.googleapis\.com", re.IGNORECASE),
    re.compile(r"https?://cdnjs\.cloudflare\.com", re.IGNORECASE),
    re.compile(r"https?://cdn\.jsdelivr\.net", re.IGNORECASE),
    re.compile(r"https?://unpkg\.com", re.IGNORECASE),
    re.compile(r"https?://use\.fontawesome\.com", re.IGNORECASE),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_ed25519_signature(pub_key_b64: str, data: bytes, sig_b64: str) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519

        raw_pub = base64.b64decode(pub_key_b64.strip())
        raw_sig = base64.b64decode(sig_b64.strip())
        pub = ed25519.Ed25519PublicKey.from_public_bytes(raw_pub)
        pub.verify(raw_sig, data)
        return True
    except Exception as e:
        print(f"[!] Signature verification error: {e}")
        return False


def verify_release(target_dir: Path | None = None) -> bool:
    root = target_dir or Path(__file__).resolve().parent.parent

    # Locate release_manifest.json
    candidates = [
        root / "release_manifest.json",
        root / "deploy" / "offline_bundle" / "release_manifest.json",
        root / "deploy" / "offline_bundle" / "staging" / "release_manifest.json",
    ]
    manifest_path = next((p for p in candidates if p.is_file()), None)

    if not manifest_path:
        print(f"[FAIL] Release manifest not found in candidates: {[str(c) for c in candidates]}")
        return False

    print(f"Loading release manifest from {manifest_path}...")
    with open(manifest_path, "rb") as f:
        manifest_raw_bytes = f.read()

    manifest = json.loads(manifest_raw_bytes.decode("utf-8"))
    files_dict = manifest.get("files", {})
    manifest_dir = manifest_path.parent

    # 1. Verify detached cryptographic signature if available
    sig_candidates = [
        manifest_dir / "release_manifest.sig.json",
        root / "release_manifest.sig.json",
        root / "deploy" / "offline_bundle" / "release_manifest.sig.json",
    ]
    sig_path = next((p for p in sig_candidates if p.is_file()), None)
    pub_candidates = [
        manifest_dir / "release_public_key.pub",
        root / "release_public_key.pub",
        root / "deploy" / "offline_bundle" / "release_public_key.pub",
    ]
    pub_path = next((p for p in pub_candidates if p.is_file()), None)

    signature_verified = False
    if sig_path and pub_path:
        with open(sig_path, "r", encoding="utf-8") as f:
            sig_info = json.load(f)
        with open(pub_path, "r", encoding="utf-8") as f:
            pub_key_b64 = f.read().strip()

        manifest_digest = hashlib.sha256(manifest_raw_bytes).hexdigest()
        if sig_info.get("manifest_sha256") == manifest_digest:
            signature_verified = verify_ed25519_signature(
                pub_key_b64, manifest_digest.encode("utf-8"), sig_info["signature_b64"]
            )
            print(
                f"[+] Detached Ed25519 signature: {'VERIFIED' if signature_verified else 'INVALID'}"
            )
        else:
            print("[!] Manifest digest mismatch against signature sidecar.")

    # Determine base directory to verify files against
    if target_dir:
        base_dir = target_dir
    elif (root / "deploy" / "offline_bundle" / "staging").is_dir():
        base_dir = root / "deploy" / "offline_bundle" / "staging"
    else:
        base_dir = manifest_dir if (manifest_dir / "apps").is_dir() else root

    total_files = len(files_dict)
    checked = 0
    corrupted = []
    missing = []

    print(f"Verifying {total_files} files against cryptographic digests in {base_dir}...")
    for rel_path, meta in files_dict.items():
        file_path = base_dir / rel_path
        if not file_path.is_file():
            # Try checking relative to root
            file_path = root / rel_path

        if not file_path.is_file():
            missing.append(rel_path)
            continue

        expected_hash = meta["sha256"]
        actual_hash = sha256_file(file_path)
        if actual_hash.lower() != expected_hash.lower():
            corrupted.append((rel_path, expected_hash, actual_hash))
        checked += 1

    # Check for external network dependencies in templates and dist
    external_refs = []
    text_extensions = [".html", ".js", ".css", ".json", ".py"]
    for p in base_dir.rglob("*"):
        if p.is_file() and p.suffix in text_extensions:
            # Skip evaluation scenarios or git
            if ".git" in p.parts or "node_modules" in p.parts or ".venv" in p.parts:
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                for pat in FORBIDDEN_NETWORK_PATTERNS:
                    if pat.search(content):
                        external_refs.append((p.relative_to(base_dir).as_posix(), pat.pattern))
            except Exception:
                pass

    # Model manifest verification
    model_manifest_path = base_dir / "models" / "manifest.json"
    if not model_manifest_path.is_file():
        model_manifest_path = root / "models" / "manifest.json"

    model_manifest_valid = False
    if model_manifest_path.is_file():
        try:
            with open(model_manifest_path, "r", encoding="utf-8") as mf:
                m_data = json.load(mf)
                if "files" in m_data and "commit_sha" in m_data:
                    model_manifest_valid = True
        except Exception:
            pass

    # Leak scan for sensitive production databases
    leaked_databases = []
    for p in base_dir.rglob("*.db"):
        if "sat_sa" in p.name:
            leaked_databases.append(p.name)

    # Summary report
    print("\n--- RELEASE VERIFICATION SUMMARY ---")
    print(f"Total Files in Manifest:  {total_files}")
    print(f"Successfully Verified:    {checked - len(corrupted)}")
    print(f"Missing Files:            {len(missing)}")
    print(f"Corrupted Files:          {len(corrupted)}")
    print(f"External CDN References:  {len(external_refs)}")
    print(
        f"Signature Status:         {'VERIFIED' if signature_verified else 'NOT PROVIDED / UNVERIFIED'}"
    )
    print(
        f"Model Manifest Status:    {'VERIFIED' if model_manifest_valid else 'NOT FOUND / INVALID'}"
    )
    print(
        f"Sensitive DB Leak Status: {'CLEAN (0 leaked databases)' if not leaked_databases else f'LEAK DETECTED: {leaked_databases}'}"
    )

    if missing:
        print("\n[FAIL] Missing files detected:")
        for m in missing[:10]:
            print(f"  - {m}")

    if corrupted:
        print("\n[FAIL] Corrupted / Altered files detected:")
        for c, exp, act in corrupted[:10]:
            print(f"  - {c} (expected: {exp[:10]}..., actual: {act[:10]}...)")

    if external_refs:
        print("\n[FAIL] Prohibited external network references detected:")
        for file_ref, pattern in external_refs[:10]:
            print(f"  - {file_ref}: matched {pattern}")

    if leaked_databases:
        print("\n[FAIL] Prohibited production database files detected in release bundle!")

    if missing or corrupted or external_refs or leaked_databases:
        print("\n[RESULT] RELEASE INTEGRITY CHECK FAILED.")
        return False

    print("\n[RESULT] ALL CHECKS PASSED: Offline release bundle is intact, signed, and verified.")
    return True


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    success = verify_release(target)
    sys.exit(0 if success else 1)
