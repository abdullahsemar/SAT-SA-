# SAT-SA Offline Release Bundle & Operations Manual

This package contains the complete, self-contained offline deployment of the **Supervisory Analytics Tool for SOC Assessment (SAT-SA)**.

## 1. Architectural Guarantee: 100% Offline Runtime
Per `docs/BUILD_RULES.md`:
- All components operate on loopback (`127.0.0.1` / `localhost`).
- Zero remote telemetry, external CDNs, Google Fonts, or cloud model endpoints.
- The semantic similarity engine runs locally using the pinned `all-MiniLM-L6-v2` transformer weights in `models/` or deterministic lexical fallback.

---

## 2. Release Verification

Before deploying, verify the release archive against the cryptographic manifest:

```bash
python scripts/verify_release.py
```

The verification script checks:
1. Every file matches its published SHA-256 digest in `release_manifest.json`.
2. No prohibited external URLs or CDNs are referenced in HTML templates or bundle scripts.
3. Offline model manifest is intact.

If any file is missing or altered, the script exits with code `1`.

---

## 3. Fresh Offline Installation & Startup

### Option A: Local Python / Node Environment
1. Extract the release archive into an offline directory.
2. Ensure Python 3.11+ and dependencies are installed from local wheel cache:
   ```bash
   pip install --no-index --find-links=./wheels .
   ```
3. Run database migrations:
   ```bash
   alembic upgrade head
   ```
4. Start backend API on loopback:
   ```bash
   uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
   ```
5. Serve the prebuilt web UI:
   ```bash
   npx serve -s apps/web/dist -l 5173
   ```
6. Open your browser to `http://127.0.0.1:5173`.

### Option B: Isolated Docker Compose
Execute the isolated Docker Compose configuration (configured with `internal: true` bridge network without an internet gateway):

```bash
docker compose -f deploy/compose.yaml up -d
```
Access the application at `http://127.0.0.1:8080`.

---

## 4. Backup & Disaster Recovery

### Backup Procedure
1. Stop runtime writes or place database in read-only mode:
   ```bash
   sqlite3 storage/sat_sa.db "VACUUM INTO 'backup/sat_sa_backup.db';"
   ```
2. Archive the evidence storage directory:
   ```bash
   tar -czf backup/evidence_store_$(date +%F).tar.gz storage/
   ```
3. Compute and store backup checksums:
   ```bash
   sha256sum backup/* > backup/checksums.sha256
   ```

### Restore Procedure
1. Verify backup archive integrity:
   ```bash
   sha256sum -c backup/checksums.sha256
   ```
2. Restore database:
   ```bash
   cp backup/sat_sa_backup.db storage/sat_sa.db
   ```
3. Restore evidence store:
   ```bash
   tar -xzf backup/evidence_store_*.tar.gz -C storage/
   ```

---

## 5. Security & Storage Disclosures
- **Encryption at Rest**: Standard SQLite databases and file stores are **unencrypted** by default. Production regulatory deployments **must** host the application and `/data` storage volume on operating-system-level encrypted partitions (e.g., BitLocker, LUKS, or dm-crypt).
- **Audit Immutability**: Application-level audit records (`review_audit_events`, `review_decisions`, `assessment_reports`) use software-enforced append-only constraints. They do not constitute a hardware-enforced Write-Once-Read-Many (WORM) or administrator-proof cryptographic blockchain.
