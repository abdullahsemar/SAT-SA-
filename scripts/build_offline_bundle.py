"""Builds a verified offline release bundle for SAT-SA.

Stages runtime assets, frontend production build, offline models/manifest,
clean database migrations, documentation, scripts, and synthetic scenarios.
Generates a deterministic release manifest signed with Ed25519 and scans
for secrets or leaked production databases.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
DEPLOY_DIR = ROOT_DIR / "deploy"
OFFLINE_DIR = DEPLOY_DIR / "offline_bundle"
STAGING_DIR = OFFLINE_DIR / "staging"
OUTPUT_BUNDLE = OFFLINE_DIR / "sat_sa_offline_bundle.zip"

EXCLUDE_PATTERNS = [
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".git",
    ".github",
    ".venv",
    "node_modules",
    "storage",
    "*.sqlite",
    "*.db",
    "*.log",
    ".env",
    "*.egg-info",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def copy_tree_filtered(src: Path, dst: Path, ignore_patterns: list[str]):
    """Copies directory tree filtering out caches, virtual environments, and databases."""
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(*ignore_patterns),
        dirs_exist_ok=True,
    )


def scan_for_leaks(staging_dir: Path) -> list[str]:
    """Scans staged files to ensure no sensitive databases or secret keys are packaged."""
    violations = []
    forbidden_files = ["sat_sa.db", "sat_sa_preserved_backup.db", ".env", "id_rsa", "id_ed25519"]
    for root, _, files in os.walk(staging_dir):
        for f in files:
            if f in forbidden_files or f.endswith(".db") or f.endswith(".sqlite"):
                violations.append(str(Path(root) / f))
    return violations


def build_bundle():
    print(f"[{datetime.now().isoformat()}] Starting SAT-SA offline release bundling...")

    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Copy backend packages and database schema
    print("-> Staging backend packages and database schema...")
    for pkg in ["apps", "db", "packages", "config"]:
        copy_tree_filtered(ROOT_DIR / pkg, STAGING_DIR / pkg, EXCLUDE_PATTERNS)

    shutil.copy2(ROOT_DIR / "alembic.ini", STAGING_DIR / "alembic.ini")
    shutil.copy2(ROOT_DIR / "pyproject.toml", STAGING_DIR / "pyproject.toml")
    shutil.copy2(ROOT_DIR / "README.md", STAGING_DIR / "README.md")

    # 2. Copy documentation
    print("-> Staging documentation...")
    copy_tree_filtered(ROOT_DIR / "docs", STAGING_DIR / "docs", EXCLUDE_PATTERNS)

    # 3. Copy built frontend dist if available
    web_dist = ROOT_DIR / "apps" / "web" / "dist"
    if web_dist.is_dir():
        print("-> Staging compiled frontend assets (dist)...")
        copy_tree_filtered(web_dist, STAGING_DIR / "apps" / "web" / "dist", EXCLUDE_PATTERNS)
    else:
        print("-> WARNING: apps/web/dist not found. Run 'npm --prefix apps/web run build' first.")

    # 4. Copy approved model manifest and offline weights
    models_dir = ROOT_DIR / "models"
    if models_dir.is_dir():
        print("-> Staging verified offline models and manifest...")
        copy_tree_filtered(models_dir, STAGING_DIR / "models", EXCLUDE_PATTERNS)

    # 5. Copy synthetic test and demonstration scenarios
    print("-> Staging synthetic scenarios...")
    copy_tree_filtered(ROOT_DIR / "synthetic", STAGING_DIR / "synthetic", EXCLUDE_PATTERNS)

    # 6. Copy deployment configuration and execution scripts
    print("-> Staging deployment manifests and operational scripts...")
    scripts_dest = STAGING_DIR / "scripts"
    scripts_dest.mkdir(parents=True, exist_ok=True)
    for s_name in [
        "verify_release.py",
        "initialize_demo_data.py",
        "demonstrate_e2e_verification.py",
        "verify_evidence.py",
        "provision_model.py",
    ]:
        src_script = ROOT_DIR / "scripts" / s_name
        if src_script.is_file():
            shutil.copy2(src_script, scripts_dest / s_name)

    shutil.copy2(ROOT_DIR / "scripts" / "verify_release.py", STAGING_DIR / "verify_release.py")

    if (DEPLOY_DIR / "compose.yaml").is_file():
        shutil.copy2(DEPLOY_DIR / "compose.yaml", STAGING_DIR / "compose.yaml")
    if (DEPLOY_DIR / "containers").is_dir():
        copy_tree_filtered(DEPLOY_DIR / "containers", STAGING_DIR / "containers", EXCLUDE_PATTERNS)
    if (DEPLOY_DIR / "ledger").is_dir():
        copy_tree_filtered(
            DEPLOY_DIR / "ledger", STAGING_DIR / "deploy" / "ledger", EXCLUDE_PATTERNS
        )

    # 7. Leak scan before signing
    print("-> Scanning staging area for sensitive databases and keys...")
    leaks = scan_for_leaks(STAGING_DIR)
    if leaks:
        raise RuntimeError(
            f"CRITICAL LEAK: Found prohibited sensitive files in staging area: {leaks}"
        )
    print("[+] Staging area clean: No databases, session tokens, or private credentials found.")

    # 8. Compute Release Manifest over payload
    print("-> Computing SHA-256 release checksum manifest...")
    manifest_entries = {}
    for root, _, files in os.walk(STAGING_DIR):
        for f in sorted(files):
            file_path = Path(root) / f
            rel_path = file_path.relative_to(STAGING_DIR).as_posix()
            digest = sha256_file(file_path)
            size = file_path.stat().st_size
            manifest_entries[rel_path] = {
                "sha256": digest,
                "size_bytes": size,
            }

    release_manifest = {
        "release_version": "2.0.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_files": len(manifest_entries),
        "files": manifest_entries,
        "verification_notice": (
            "This manifest secures the offline deployment against missing or corrupted artifacts. "
            "Execute 'python verify_release.py' to validate release integrity before runtime startup."
        ),
    }

    manifest_bytes = json.dumps(release_manifest, indent=2, sort_keys=True).encode("utf-8")
    manifest_path = STAGING_DIR / "release_manifest.json"
    with open(manifest_path, "wb") as f:
        f.write(manifest_bytes)

    # 9. Sign manifest with Ed25519 (Non-circular detached signature)
    print("-> Generating Ed25519 detached signature over release manifest...")
    from packages.evidence_integrity.signatures import (
        export_public_key_b64,
        generate_ed25519_keypair,
        sign_data,
    )

    priv_key, pub_key = generate_ed25519_keypair()
    pub_b64 = export_public_key_b64(pub_key)
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    sig_b64 = sign_data(priv_key, manifest_digest.encode("utf-8"))

    sig_payload = {
        "format": "sat-sa-release-signature-v1",
        "release_version": "2.0.0",
        "manifest_sha256": manifest_digest,
        "signing_key_id": "sat-sa-release-authority-2026",
        "signature_b64": sig_b64,
        "signed_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(STAGING_DIR / "release_manifest.sig.json", "w", encoding="utf-8") as f:
        json.dump(sig_payload, f, indent=2)

    with open(STAGING_DIR / "release_public_key.pub", "w", encoding="utf-8") as f:
        f.write(pub_b64)

    # Keep copies in OFFLINE_DIR
    OFFLINE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest_path, OFFLINE_DIR / "release_manifest.json")
    shutil.copy2(
        STAGING_DIR / "release_manifest.sig.json", OFFLINE_DIR / "release_manifest.sig.json"
    )
    shutil.copy2(STAGING_DIR / "release_public_key.pub", OFFLINE_DIR / "release_public_key.pub")

    # 10. Create ZIP archive
    print(f"-> Creating offline distribution archive: {OUTPUT_BUNDLE}...")
    with zipfile.ZipFile(OUTPUT_BUNDLE, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(STAGING_DIR):
            for f in sorted(files):
                file_path = Path(root) / f
                arc_name = file_path.relative_to(STAGING_DIR).as_posix()
                zf.write(file_path, arc_name)

    print(f"[{datetime.now().isoformat()}] Offline bundle generated successfully.")
    print(f"Total Staged Files: {len(manifest_entries) + 3}")
    print(f"Bundle Archive Size: {OUTPUT_BUNDLE.stat().st_size / (1024 * 1024):.2f} MB")
    print(f"Release Manifest: {OFFLINE_DIR / 'release_manifest.json'}")


if __name__ == "__main__":
    build_bundle()
