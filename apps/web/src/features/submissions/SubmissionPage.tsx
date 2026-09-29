import React, { useState, useEffect } from "react";
import {
  apiClient,
  UserProfile,
  SubmissionSummary,
  SubmissionDetail,
  QualityReport,
  RecordProvenance,
} from "../../api/client";

export const SubmissionPage: React.FC = () => {
  // Authentication State
  const [user, setUser] = useState<UserProfile | null>(null);
  const [usernameInput, setUsernameInput] = useState("");
  const [passwordInput, setPasswordInput] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  // Submissions State
  const [submissions, setSubmissions] = useState<SubmissionSummary[]>([]);
  const [activeSubmission, setActiveSubmission] = useState<SubmissionDetail | null>(null);
  const [qualityReport, setQualityReport] = useState<QualityReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // New Draft Manifest State
  const [manifestText, setManifestText] = useState("");
  const [showNewModal, setShowNewModal] = useState(false);

  // Record Inspection State
  const [inspectRecordId, setInspectRecordId] = useState("");
  const [inspectProvenance, setInspectProvenance] = useState<RecordProvenance | null>(null);
  const [inspectLoading, setInspectLoading] = useState(false);

  // Check current session on mount
  useEffect(() => {
    let isMounted = true;
    apiClient
      .getMe()
      .then((profile) => {
        if (isMounted) {
          setUser(profile);
          loadSubmissions();
        }
      })
      .catch(() => {
        if (isMounted) {
          setUser(null);
        }
      });
    return () => {
      isMounted = false;
    };
  }, []);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthLoading(true);
    setAuthError(null);
    try {
      const profile = await apiClient.login(usernameInput, passwordInput);
      setUser(profile);
      loadSubmissions();
    } catch (err: any) {
      setAuthError(err.message || "Authentication failed");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogout = async () => {
    try {
      await apiClient.logout();
    } catch {
      // Ignore
    }
    setUser(null);
    setActiveSubmission(null);
    setQualityReport(null);
  };

  const loadSubmissions = async () => {
    try {
      const res = await apiClient.listSubmissions(1, 50);
      setSubmissions(res.items);
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to load submissions");
    }
  };

  const handleCreateDraft = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setErrorMessage(null);
    try {
      const manifestObj = JSON.parse(manifestText);
      const created = await apiClient.createSubmission(manifestObj);
      setActiveSubmission(created);
      setQualityReport(null);
      setShowNewModal(false);
      setSuccessMessage(`Draft submission created for ${created.entity_id} (Rev ${created.revision})`);
      loadSubmissions();
    } catch (err: any) {
      setErrorMessage(err.message || "Invalid JSON or manifest validation failed");
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (sourceId: string, file: File) => {
    if (!activeSubmission) return;
    setLoading(true);
    setErrorMessage(null);
    try {
      await apiClient.uploadFile(activeSubmission.id, sourceId, file);
      const updated = await apiClient.getSubmission(activeSubmission.id);
      setActiveSubmission(updated);
      setSuccessMessage(`File '${file.name}' uploaded successfully for source '${sourceId}'`);
    } catch (err: any) {
      setErrorMessage(err.message || "File upload failed");
    } finally {
      setLoading(false);
    }
  };

  const handleValidate = async () => {
    if (!activeSubmission) return;
    setLoading(true);
    setErrorMessage(null);
    try {
      const report = await apiClient.validateSubmission(activeSubmission.id);
      setQualityReport(report);
      const updated = await apiClient.getSubmission(activeSubmission.id);
      setActiveSubmission(updated);
      setSuccessMessage("Validation completed successfully");
      loadSubmissions();
    } catch (err: any) {
      setErrorMessage(err.message || "Validation failed");
    } finally {
      setLoading(false);
    }
  };

  const handleCommit = async () => {
    if (!activeSubmission) return;
    setLoading(true);
    setErrorMessage(null);
    try {
      const key = `commit-${activeSubmission.id}-${Date.now()}`;
      const committed = await apiClient.commitSubmission(activeSubmission.id, key);
      setActiveSubmission(committed);
      setSuccessMessage(`Submission successfully committed and frozen (Rev ${committed.revision})`);
      loadSubmissions();
    } catch (err: any) {
      setErrorMessage(err.message || "Commit failed");
    } finally {
      setLoading(false);
    }
  };

  const handleSelectSubmission = async (id: string) => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const sub = await apiClient.getSubmission(id);
      setActiveSubmission(sub);
      if (sub.status === "validated" || sub.status === "committed") {
        const q = await apiClient.getSubmissionQuality(id);
        setQualityReport(q);
      } else {
        setQualityReport(null);
      }
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to load submission");
    } finally {
      setLoading(false);
    }
  };

  const handleInspectRecord = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inspectRecordId) return;
    setInspectLoading(true);
    setInspectProvenance(null);
    setErrorMessage(null);
    try {
      const prov = await apiClient.getRecordProvenance(inspectRecordId);
      setInspectProvenance(prov);
    } catch (err: any) {
      setErrorMessage(err.message || "Record provenance inspection failed");
    } finally {
      setInspectLoading(false);
    }
  };

  const loadSampleManifest = () => {
    const sample = {
      manifest_version: "1.0.0",
      entity_id: "CSE-BANK-01",
      period_start: "2026-01-01T00:00:00Z",
      period_end: "2026-02-01T00:00:00Z",
      source_timezone: "UTC",
      sources: [
        {
          source_id: "src-assets-csv",
          record_type: "assets",
          declared_row_count: 3,
          export_scope: "Full Asset Inventory",
          lineage: "CMDB Export",
          sampling_method: "full_population",
          is_optional: false,
        },
        {
          source_id: "src-alerts-csv",
          record_type: "alerts",
          declared_row_count: 3,
          export_scope: "Security Operations Alerts",
          lineage: "SIEM Production Cluster",
          sampling_method: "full_population",
          is_optional: false,
        },
      ],
    };
    setManifestText(JSON.stringify(sample, null, 2));
  };

  // If not logged in, render neutral login screen
  if (!user) {
    return (
      <div className="app-container" style={{ justifyContent: "center", alignItems: "center" }}>
        <div className="card" style={{ width: "100%", maxWidth: "420px" }}>
          <div className="card-header" style={{ flexDirection: "column", alignItems: "flex-start", gap: "0.5rem" }}>
            <span className="brand-badge">SAT-SA</span>
            <h1 className="card-title" style={{ fontSize: "1.3rem" }}>
              Supervisory Evidence Intake
            </h1>
            <p style={{ color: "var(--text-secondary)", fontSize: "0.85rem" }}>
              Offline Supervisory Analytics Tool for SOC Assessment
            </p>
          </div>

          {authError && <div className="alert-box alert-error">{authError}</div>}

          <form onSubmit={handleLogin}>
            <div className="form-group">
              <label className="form-label" htmlFor="username">
                Examiner Username
              </label>
              <input
                id="username"
                className="form-input"
                type="text"
                value={usernameInput}
                onChange={(e) => setUsernameInput(e.target.value)}
                placeholder="e.g. admin or examiner"
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                className="form-input"
                type="password"
                value={passwordInput}
                onChange={(e) => setPasswordInput(e.target.value)}
                placeholder="••••••••"
                required
              />
            </div>

            <button
              id="login-button"
              type="submit"
              className="btn btn-primary"
              style={{ width: "100%", marginTop: "0.5rem" }}
              disabled={authLoading}
            >
              {authLoading ? <span className="spinner" /> : "Sign In to Workbench"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      {/* Top Navigation */}
      <header className="top-nav">
        <div className="brand-section">
          <span className="brand-badge">SAT-SA</span>
          <span className="brand-title">Supervisory Evidence Intake Workbench</span>
        </div>
        <div className="user-status">
          <div className="user-tag">
            <span style={{ color: "var(--text-muted)", marginRight: "0.4rem" }}>Examiner:</span>
            <strong>{user.username}</strong> ({user.role})
          </div>
          <div className="user-tag">
            <span style={{ color: "var(--text-muted)", marginRight: "0.4rem" }}>Scope:</span>
            <code>{user.entity_scope.join(", ")}</code>
          </div>
          <button id="logout-btn" onClick={handleLogout} className="btn btn-secondary btn-sm">
            Sign Out
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="main-content">
        {errorMessage && (
          <div className="alert-box alert-error" role="alert">
            <span>{errorMessage}</span>
          </div>
        )}
        {successMessage && (
          <div className="alert-box alert-success" role="status">
            <span>{successMessage}</span>
          </div>
        )}

        {/* Action Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
          <div>
            <h2 style={{ fontSize: "1.5rem", fontWeight: 700 }}>CSE Evidence Submissions</h2>
            <p style={{ color: "var(--text-secondary)", fontSize: "0.85rem" }}>
              Import, parse, and verify offline periodic CSE operational evidence submissions
            </p>
          </div>
          <button
            id="new-submission-btn"
            onClick={() => {
              loadSampleManifest();
              setShowNewModal(true);
            }}
            className="btn btn-primary"
          >
            + Import New Submission
          </button>
        </div>

        {/* Active Submission View */}
        {activeSubmission ? (
          <div className="card">
            <div className="card-header">
              <div>
                <span
                  className={`badge badge-${activeSubmission.status}`}
                  style={{ marginRight: "0.75rem" }}
                  id="submission-status-badge"
                >
                  {activeSubmission.status}
                </span>
                <strong style={{ fontSize: "1.1rem" }}>{activeSubmission.entity_id}</strong>
                <span style={{ color: "var(--text-muted)", marginLeft: "0.75rem" }}>
                  Revision {activeSubmission.revision}
                </span>
              </div>
              <div style={{ display: "flex", gap: "0.75rem" }}>
                <button
                  id="validate-btn"
                  onClick={handleValidate}
                  className="btn btn-secondary"
                  disabled={loading || activeSubmission.status === "committed"}
                >
                  {loading ? <span className="spinner" /> : "Validate Quality"}
                </button>
                <button
                  id="commit-btn"
                  onClick={handleCommit}
                  className="btn btn-success"
                  disabled={loading || activeSubmission.status !== "validated"}
                >
                  Freeze & Commit Revision
                </button>
              </div>
            </div>

            {/* Scope Metadata */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(4, 1fr)",
                gap: "1rem",
                padding: "1rem",
                background: "var(--bg-surface-elevated)",
                borderRadius: "6px",
                marginBottom: "1.5rem",
                fontSize: "0.85rem",
              }}
            >
              <div>
                <span style={{ color: "var(--text-secondary)" }}>Period Start:</span>
                <div>{new Date(activeSubmission.period_start).toUTCString()}</div>
              </div>
              <div>
                <span style={{ color: "var(--text-secondary)" }}>Period End:</span>
                <div>{new Date(activeSubmission.period_end).toUTCString()}</div>
              </div>
              <div>
                <span style={{ color: "var(--text-secondary)" }}>Timezone:</span>
                <div>{activeSubmission.source_timezone}</div>
              </div>
              <div>
                <span style={{ color: "var(--text-secondary)" }}>Committed At:</span>
                <div>
                  {activeSubmission.committed_at
                    ? new Date(activeSubmission.committed_at).toUTCString()
                    : "Not Committed (Draft)"}
                </div>
              </div>
            </div>

            {/* Evidence Quality Scorecard (if validated/committed) */}
            {qualityReport && (
              <div style={{ marginBottom: "2rem" }}>
                <h3 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "1rem" }}>
                  Evidence Quality Scorecard
                </h3>
                <div className="stats-grid">
                  <div className="stat-box success">
                    <span className="stat-label">Accepted Records</span>
                    <span className="stat-value" id="stat-accepted-count">{qualityReport.accepted_count}</span>
                  </div>
                  <div className="stat-box danger">
                    <span className="stat-label">Rejected / Quarantined</span>
                    <span className="stat-value" id="stat-rejected-count">{qualityReport.rejected_count}</span>
                  </div>
                  <div className="stat-box warning">
                    <span className="stat-label">Duplicate IDs</span>
                    <span className="stat-value" id="stat-duplicate-count">{qualityReport.duplicate_count}</span>
                  </div>
                  <div className="stat-box danger">
                    <span className="stat-label">Orphan Links</span>
                    <span className="stat-value" id="stat-orphan-count">{qualityReport.orphan_count}</span>
                  </div>
                  <div className="stat-box purple">
                    <span className="stat-label">Timestamp Issues</span>
                    <span className="stat-value" id="stat-timestamp-count">{qualityReport.timestamp_problem_count}</span>
                  </div>
                </div>

                {/* Source Completeness Table */}
                <h4 style={{ fontSize: "0.9rem", fontWeight: 600, margin: "1rem 0 0.5rem" }}>
                  Declared vs. Reconciled Source Coverage
                </h4>
                <div className="table-responsive">
                  <table className="data-table" id="source-coverage-table">
                    <thead>
                      <tr>
                        <th>Source ID</th>
                        <th>Record Type</th>
                        <th>Declared Rows</th>
                        <th>Actual Rows</th>
                        <th>Completeness Status</th>
                        <th>SHA-256 Hash</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.values(qualityReport.source_summaries).map((s) => (
                        <tr key={s.source_id}>
                          <td><code>{s.source_id}</code></td>
                          <td><span className="badge badge-info">{s.record_type}</span></td>
                          <td>{s.declared_rows}</td>
                          <td>{s.actual_rows}</td>
                          <td>
                            <span
                              className={`badge ${
                                s.status === "PRESENT"
                                  ? "badge-committed"
                                  : s.status === "UNKNOWN"
                                  ? "badge-unknown"
                                  : "badge-error"
                              }`}
                            >
                              {s.status} {s.is_optional && "(Optional)"}
                            </span>
                          </td>
                          <td>
                            <code style={{ fontSize: "0.75rem" }}>
                              {s.sha256 ? `${s.sha256.substring(0, 16)}...` : "—"}
                            </code>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Issues List */}
                {qualityReport.issues.length > 0 && (
                  <div style={{ marginTop: "1.5rem" }}>
                    <h4 style={{ fontSize: "0.9rem", fontWeight: 600, marginBottom: "0.5rem" }}>
                      Quality Discrepancies & Issues ({qualityReport.issues.length})
                    </h4>
                    <div className="table-responsive">
                      <table className="data-table" id="quality-issues-table">
                        <thead>
                          <tr>
                            <th>Severity</th>
                            <th>Issue Type</th>
                            <th>Source</th>
                            <th>Locator</th>
                            <th>Field</th>
                            <th>Message</th>
                          </tr>
                        </thead>
                        <tbody>
                          {qualityReport.issues.map((i, idx) => (
                            <tr key={i.id || idx}>
                              <td>
                                <span className={`badge badge-${i.severity}`}>{i.severity}</span>
                              </td>
                              <td><code>{i.issue_type}</code></td>
                              <td>{i.source_id || "—"}</td>
                              <td>{i.row_locator || "—"}</td>
                              <td>{i.field_name || "—"}</td>
                              <td>{i.message}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Declared File Uploads */}
            <div>
              <h3 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "0.75rem" }}>
                Declared Evidence Files
              </h3>
              <div className="table-responsive">
                <table className="data-table" id="evidence-files-table">
                  <thead>
                    <tr>
                      <th>Source ID</th>
                      <th>Record Type</th>
                      <th>Uploaded Filename</th>
                      <th>Size</th>
                      <th>Declared Rows</th>
                      <th>Actual Rows</th>
                      <th>Upload / Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeSubmission.manifest.sources.map((src: any) => {
                      const fileRecord = activeSubmission.files.find((f) => f.source_id === src.source_id);
                      return (
                        <tr key={src.source_id}>
                          <td><code>{src.source_id}</code></td>
                          <td><span className="badge badge-info">{src.record_type}</span></td>
                          <td>{fileRecord ? fileRecord.original_filename : <span style={{ color: "var(--text-muted)" }}>Not uploaded</span>}</td>
                          <td>{fileRecord ? `${(fileRecord.byte_size / 1024).toFixed(1)} KB` : "—"}</td>
                          <td>{src.declared_row_count}</td>
                          <td>{fileRecord ? fileRecord.actual_row_count : "—"}</td>
                          <td>
                            {activeSubmission.status === "committed" ? (
                              <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>Locked</span>
                            ) : (
                              <input
                                type="file"
                                id={`file-input-${src.source_id}`}
                                accept=".csv,.json,.jsonl,.ndjson"
                                onChange={(e) => {
                                  if (e.target.files && e.target.files[0]) {
                                    handleFileUpload(src.source_id, e.target.files[0]);
                                  }
                                }}
                                style={{ fontSize: "0.8rem" }}
                              />
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        ) : null}

        {/* Past Submissions History Table */}
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Saved CSE Submissions</h3>
            <button onClick={loadSubmissions} className="btn btn-secondary btn-sm">
              Refresh
            </button>
          </div>
          {submissions.length === 0 ? (
            <div style={{ textAlign: "center", padding: "2rem", color: "var(--text-muted)" }}>
              No submissions found for your entity scope. Import a new submission to begin.
            </div>
          ) : (
            <div className="table-responsive">
              <table className="data-table" id="submissions-history-table">
                <thead>
                  <tr>
                    <th>Entity ID</th>
                    <th>Status</th>
                    <th>Revision</th>
                    <th>Files</th>
                    <th>Period Range</th>
                    <th>Created At</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {submissions.map((sub) => (
                    <tr key={sub.id}>
                      <td><strong>{sub.entity_id}</strong></td>
                      <td><span className={`badge badge-${sub.status}`}>{sub.status}</span></td>
                      <td>Rev {sub.revision}</td>
                      <td>{sub.file_count} files</td>
                      <td style={{ fontSize: "0.8rem" }}>
                        {new Date(sub.period_start).toLocaleDateString()} — {new Date(sub.period_end).toLocaleDateString()}
                      </td>
                      <td style={{ fontSize: "0.8rem" }}>{new Date(sub.created_at).toLocaleString()}</td>
                      <td>
                        <button
                          id={`reopen-btn-${sub.id}`}
                          onClick={() => handleSelectSubmission(sub.id)}
                          className="btn btn-secondary btn-sm"
                        >
                          Open Submission
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Record Provenance Inspector Drawer */}
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Evidence Record Provenance Inspector</h3>
          </div>
          <form onSubmit={handleInspectRecord} style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem" }}>
            <input
              id="inspect-record-input"
              className="form-input"
              type="text"
              value={inspectRecordId}
              onChange={(e) => setInspectRecordId(e.target.value)}
              placeholder="Enter Normalized Record UUID to inspect source row & provenance"
              required
              style={{ maxWidth: "550px" }}
            />
            <button id="inspect-submit-btn" type="submit" className="btn btn-secondary" disabled={inspectLoading}>
              {inspectLoading ? <span className="spinner" /> : "Inspect Record"}
            </button>
          </form>

          {inspectProvenance && (
            <div id="provenance-detail-card" style={{ background: "var(--bg-surface-elevated)", padding: "1.25rem", borderRadius: "8px" }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1rem", marginBottom: "1rem", fontSize: "0.85rem" }}>
                <div><strong>Entity:</strong> {inspectProvenance.entity_id}</div>
                <div><strong>Source ID:</strong> <code>{inspectProvenance.source_id}</code></div>
                <div><strong>Record Type:</strong> {inspectProvenance.record_type}</div>
                <div><strong>Native ID:</strong> <code>{inspectProvenance.native_id}</code></div>
                <div><strong>Row Locator:</strong> <code>{inspectProvenance.row_locator}</code></div>
                <div><strong>SHA-256 Hash:</strong> <code style={{ fontSize: "0.75rem" }}>{inspectProvenance.raw_sha256}</code></div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                <div>
                  <span style={{ fontSize: "0.8rem", color: "var(--text-secondary)", fontWeight: 600 }}>
                    ORIGINAL RAW SOURCE PAYLOAD (From Extracted Evidence)
                  </span>
                  <pre className="code-preview" id="raw-payload-preview">
                    {JSON.stringify(inspectProvenance.raw_payload, null, 2)}
                  </pre>
                </div>
                <div>
                  <span style={{ fontSize: "0.8rem", color: "var(--text-secondary)", fontWeight: 600 }}>
                    CANONICAL NORMALIZED TYPED RECORD
                  </span>
                  <pre className="code-preview" id="normalized-payload-preview">
                    {JSON.stringify(inspectProvenance.normalized_data, null, 2)}
                  </pre>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* New Submission Modal */}
      {showNewModal && (
        <div className="modal-backdrop">
          <div className="modal-dialog">
            <div className="modal-header">
              <h3 className="card-title">Import CSE Evidence Manifest</h3>
              <button onClick={() => setShowNewModal(false)} className="btn btn-secondary btn-sm">
                ✕
              </button>
            </div>
            <form onSubmit={handleCreateDraft}>
              <div className="modal-body">
                <p style={{ color: "var(--text-secondary)", fontSize: "0.85rem", marginBottom: "1rem" }}>
                  Paste the JSON manifest declaring the evaluation period, source systems, expected record types,
                  and export scopes.
                </p>
                <div className="form-group">
                  <textarea
                    id="manifest-textarea"
                    className="form-textarea"
                    rows={12}
                    value={manifestText}
                    onChange={(e) => setManifestText(e.target.value)}
                    required
                    style={{ fontFamily: "var(--font-mono)", fontSize: "0.85rem" }}
                  />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" onClick={() => setShowNewModal(false)} className="btn btn-secondary">
                  Cancel
                </button>
                <button id="submit-manifest-btn" type="submit" className="btn btn-primary" disabled={loading}>
                  {loading ? <span className="spinner" /> : "Create Draft Submission"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default SubmissionPage;
