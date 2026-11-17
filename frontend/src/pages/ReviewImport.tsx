import React, { useEffect, useState } from "react";
import {
  AlertTriangle,
  Check,
  Copy,
  ExternalLink,
  Layers,
  Link2,
  RefreshCw,
  Sparkles,
  Trash2,
  UserCheck,
} from "lucide-react";
import { apiFetch } from "../api/client";

interface ReviewImportProps {
  jobId: number;
  onSelectOtherJob?: (otherJobId: number) => void;
  onApplied: (profileId: number) => void;
  onCancel: () => void;
}

const FIELD_LABELS: Record<string, string> = {
  full_name: "Full Name",
  age: "Age",
  dob: "Date of Birth",
  time_of_birth: "Time of Birth (Kundli)",
  place_of_birth: "Place of Birth (Kundli)",
  height: "Height",
  marital_status: "Marital Status",
  diet: "Diet / Lifestyle",
  smoking_drinking: "Smoking / Drinking",
  education: "Highest Education",
  college: "College / University",
  occupation: "Occupation / Role",
  company: "Company / Employer",
  annual_ctc: "Annual Package (CTC / LPA)",
  work_mode: "Work Mode",
  current_city: "Current City",
  hometown: "Hometown / Native Place",
  relocation_openness: "Relocation Openness",
  father_details: "Father's Details",
  mother_details: "Mother's Details",
  siblings_details: "Siblings Details",
  family_type: "Family Type",
  family_location: "Family Location",
  caste_community: "Community / Caste",
  sub_caste: "Sub-caste",
  gotra: "Gotra",
  manglik: "Manglik Status",
  kundli_status: "Kundli Match Status",
  kundli_gunas: "Kundli Gunas",
  kundli_notes: "Kundli Notes",
  source_channel: "Source Channel",
  source_name: "Referred By (Relative / Mediator)",
  source_phone: "Mediator Phone",
  primary_contact_name: "Primary Family Contact",
  primary_contact_relation: "Contact Relation",
  primary_contact_phone: "Family Contact Phone",
  candidate_phone: "Candidate Direct Phone",
  linkedin_or_social: "LinkedIn / Social",
  avatar_url: "Extracted Portrait Photo",
};

export const ReviewImport: React.FC<ReviewImportProps> = ({
  jobId,
  onSelectOtherJob,
  onApplied,
  onCancel,
}) => {
  const [job, setJob] = useState<any>(null);
  const [editedFields, setEditedFields] = useState<Record<string, any>>({});
  const [checkedFields, setCheckedFields] = useState<Record<string, boolean>>({});
  const [bulkRows, setBulkRows] = useState<any[]>([]);
  const [selectedTargetId, setSelectedTargetId] = useState<number | null>(null);
  const [createFollowUp, setCreateFollowUp] = useState<boolean>(true);
  const [followUpTask, setFollowUpTask] = useState<string>("");
  const [copiedReplyKey, setCopiedReplyKey] = useState<string | null>(null);
  const [saving, setSaving] = useState<boolean>(false);

  const loadJob = async () => {
    const data = await apiFetch<any>(`/api/imports/${jobId}`);
    setJob(data);
    const ext = data.extracted || {};
    if (Array.isArray(ext.bulk_candidates) && ext.bulk_candidates.length >= 2) {
      setBulkRows(ext.bulk_candidates);
    } else {
      setBulkRows([]);
    }
    const extFields = ext.extracted_fields || {};
    const nonEmpty: Record<string, any> = {};
    const checks: Record<string, boolean> = {};
    Object.entries(extFields).forEach(([k, v]) => {
      if (v !== null && v !== undefined && v !== "") {
        nonEmpty[k] = v;
        checks[k] = true;
      }
    });
    setEditedFields(nonEmpty);
    setCheckedFields(checks);
    setSelectedTargetId(data.target_profile_id || null);
    setFollowUpTask(
      ext.suggested_follow_up?.task ||
        "Review extracted profile & decide next step with family"
    );
  };

  useEffect(() => {
    loadJob();
  }, [jobId]);

  // Auto-poll if Mac AI Worker is currently processing this upload in the background
  useEffect(() => {
    if (!job?.extracted?.pending_mac_ai) return;
    const timer = window.setInterval(() => {
      apiFetch<any>(`/api/imports/${jobId}`).then((data) => {
        if (!data.extracted?.pending_mac_ai) {
          setJob(data);
          if (Array.isArray(data.extracted?.bulk_candidates) && data.extracted.bulk_candidates.length >= 2) {
            setBulkRows(data.extracted.bulk_candidates);
          }
          const extFields = data.extracted?.extracted_fields || {};
          const nonEmpty: Record<string, any> = {};
          const checks: Record<string, boolean> = {};
          Object.entries(extFields).forEach(([k, v]) => {
            if (v !== null && v !== undefined && v !== "") {
              nonEmpty[k] = v;
              checks[k] = true;
            }
          });
          setEditedFields(nonEmpty);
          setCheckedFields(checks);
          setSelectedTargetId(data.target_profile_id || null);
        }
      });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [job?.extracted?.pending_mac_ai, jobId]);

  if (!job) {
    return <div className="card">Loading staged AI extraction #{jobId}...</div>;
  }

  const ext = job.extracted || {};
  const isBulkList = bulkRows.length >= 2;
  const duplicates: any[] = ext.duplicate_matches || [];
  const modelsUsed: Record<string, string> = ext.models_used || {};
  const replies: Record<string, string> = ext.draft_whatsapp_replies || {};
  const provenance: Record<string, string> = ext.field_provenance || {};
  const targetProfile = job.target_profile || {};
  const allExistingProfiles: any[] = job.all_existing_profiles || [];
  const pendingQueue: any[] = job.pending_queue || [];
  const aiAutoLinkReason: string | null = ext.ai_auto_link_reason || null;

  const handleApplySingle = async () => {
    setSaving(true);
    try {
      const accepted: Record<string, any> = {};
      Object.entries(editedFields).forEach(([k, v]) => {
        if (checkedFields[k] && v !== "" && v !== null) {
          accepted[k] = v;
        }
      });
      if (ext.suggested_status && !accepted.status) {
        accepted.status = ext.suggested_status;
      }
      if (ext.suggested_ball_in_court && !accepted.ball_in_court) {
        accepted.ball_in_court = ext.suggested_ball_in_court;
      }

      const res = await apiFetch<{ profile_id: number }>(`/api/imports/${jobId}/apply`, {
        method: "POST",
        body: JSON.stringify({
          target_profile_id: selectedTargetId,
          accepted_fields: accepted,
          positives: ext.positives || [],
          concerns: ext.concerns || [],
          missing_questions: ext.missing_questions || [],
          fit_summary: ext.fit_summary || "",
          ai_fit_score: ext.ai_fit_score,
          pre_call_brief: ext.pre_call_brief || "",
          create_follow_up: createFollowUp,
          follow_up_task: followUpTask,
        }),
      });
      onApplied(res.profile_id);
    } catch (err: any) {
      alert(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleApplyBulkBatch = async () => {
    setSaving(true);
    try {
      const res = await apiFetch<{
        created_count: number;
        updated_count: number;
        created_profile_ids: number[];
        updated_profile_ids: number[];
      }>(`/api/imports/${jobId}/apply-batch`, {
        method: "POST",
        body: JSON.stringify({ rows: bulkRows }),
      });
      alert(
        `Processed Register Batch! Created ${res.created_count} New Profile(s) and Updated ${res.updated_count} Existing Profile(s).`
      );
      onCancel();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleReject = async () => {
    await apiFetch(`/api/imports/${jobId}/reject`, { method: "POST" });
    onCancel();
  };

  const updateBulkRowField = (idx: number, fieldKey: string, val: any) => {
    setBulkRows((prev) =>
      prev.map((r, i) => (i === idx ? { ...r, fields: { ...r.fields, [fieldKey]: val } } : r))
    );
  };

  const updateBulkRowMeta = (idx: number, metaUpdates: Record<string, any>) => {
    setBulkRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...metaUpdates } : r)));
  };

  const copyReply = async (key: string, text: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedReplyKey(key);
    setTimeout(() => setCopiedReplyKey(null), 2500);
  };

  const selectedBulkCount = bulkRows.filter((r) => r.selected !== false).length;
  const newBulkCount = bulkRows.filter((r) => r.selected !== false && !r.matched_profile_id).length;
  const matchedBulkCount = bulkRows.filter((r) => r.selected !== false && r.matched_profile_id).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
      {/* Multi-Candidate Segregated Review Queue Switcher */}
      {pendingQueue.length > 1 && (
        <div
          className="card"
          style={{
            background: "var(--color-indigo-soft)",
            borderColor: "var(--color-indigo)",
            display: "flex",
            flexDirection: "column",
            gap: "0.5rem",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}>
            <strong>
              <Layers size={15} style={{ verticalAlign: "middle" }} /> AI Segregated {pendingQueue.length} Upload
              Batches for Your Review
            </strong>
            <span className="mono-label">Switch between staged imports</span>
          </div>
          <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
            {pendingQueue.map((item, idx) => (
              <button
                key={item.id}
                type="button"
                className={`btn btn-sm ${item.id === jobId ? "btn-primary" : ""}`}
                onClick={() => onSelectOtherJob?.(item.id)}
              >
                #{idx + 1}: {item.candidate_name}{" "}
                {item.target_profile_id ? `[Linked -> Profile #${item.target_profile_id}]` : "[New]"}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Header Banner */}
      <div className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "0.75rem" }}>
        <div>
          <div className="mono-label">Human-in-the-Loop AI Staging · Import #{jobId}</div>
          <h1 style={{ fontSize: "1.45rem" }}>
            {isBulkList
              ? `Handwritten Diary / Multi-Row Register (${bulkRows.length} Candidates Detected)`
              : `Review Extracted Details: ${editedFields.full_name || "New Prospect"}`}
          </h1>
          <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", marginTop: "0.4rem" }}>
            {Object.entries(modelsUsed).map(([stage, m]) => (
              <span key={stage} className="badge badge-indigo">
                <Sparkles size={11} /> {stage}: {m}
              </span>
            ))}
            {ext.pending_mac_ai && (
              <span className="badge badge-amber">
                <RefreshCw size={11} /> Waiting for Mac AI Vision Worker (Auto-refreshing...)
              </span>
            )}
          </div>
        </div>

        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <button type="button" className="btn" data-state="error" onClick={handleReject}>
            <Trash2 size={15} /> Discard Import
          </button>
          {isBulkList ? (
            <button
              type="button"
              className="btn btn-primary"
              disabled={saving || selectedBulkCount === 0}
              data-state={saving ? "loading" : undefined}
              onClick={handleApplyBulkBatch}
            >
              <Check size={16} />{" "}
              {saving
                ? "Creating & Updating Profiles..."
                : `Approve All (${newBulkCount} New + ${matchedBulkCount} Existing Updates)`}
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              disabled={saving}
              data-state={saving ? "loading" : undefined}
              onClick={handleApplySingle}
            >
              <Check size={16} />{" "}
              {selectedTargetId
                ? `Approve & Merge into Profile #${selectedTargetId}`
                : "Approve & Save as New Profile"}
            </button>
          )}
        </div>
      </div>

      {/* BULK DIARY / REGISTER TABLE VIEW (When 2+ rows extracted from image/spreadsheet/text) */}
      {isBulkList ? (
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
            <div>
              <h2 style={{ fontSize: "1.18rem" }}>
                Segregated Candidates Cross-Checked Against Database ({bulkRows.length} Rows)
              </h2>
              <p style={{ margin: "0.2rem 0 0", fontSize: "0.84rem", color: "var(--color-ink-2)" }}>
                Hindi names, cities, sibling codes (<code>1B</code> = 1 Brother, <code>2S</code> = 2 Sisters), job codes (
                <code>SP</code> = Software Professional, <code>CA</code>, <code>PM</code>, <code>QAE</code>), and
                crossed-out lines have been decoded and checked against existing profiles.
              </p>
            </div>
            <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
              <span className="badge badge-sage">{newBulkCount} New Profiles to Create</span>
              <span className="badge badge-indigo">{matchedBulkCount} Matched Existing Profiles</span>
              {ext.bulk_stats?.mean_confidence && (
                <span className="badge badge-sage">
                  Mean AI/OCR Accuracy: {ext.bulk_stats.mean_confidence}%
                </span>
              )}
              {typeof ext.bulk_stats?.needs_verification_count === "number" &&
                ext.bulk_stats.needs_verification_count > 0 && (
                  <span className="badge badge-amber">
                    {ext.bulk_stats.needs_verification_count} Row(s) Flagged to Verify
                  </span>
                )}
              <button
                type="button"
                className="btn btn-sm"
                onClick={() =>
                  setBulkRows((prev) => prev.map((r) => ({ ...r, selected: !r.is_crossed_out })))
                }
              >
                Uncheck Crossed-Out Rows
              </button>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setBulkRows((prev) => prev.map((r) => ({ ...r, selected: true })))}
              >
                Select All ({bulkRows.length})
              </button>
            </div>
          </div>

          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem" }}>
              <thead>
                <tr style={{ borderBottom: "2px solid var(--color-rule-strong)", textAlign: "left" }}>
                  <th style={{ padding: "0.5rem" }}>✓</th>
                  <th style={{ padding: "0.5rem" }}>Accuracy &amp; Source</th>
                  <th style={{ padding: "0.5rem" }}>DB Match / Action</th>
                  <th style={{ padding: "0.5rem", minWidth: 190 }}>Full Name (English + Hindi)</th>
                  <th style={{ padding: "0.5rem", minWidth: 125 }}>Phone Number</th>
                  <th style={{ padding: "0.5rem", minWidth: 120 }}>City</th>
                  <th style={{ padding: "0.5rem", minWidth: 125 }}>Siblings (1B/2S)</th>
                  <th style={{ padding: "0.5rem", minWidth: 155 }}>Occupation / Code</th>
                  <th style={{ padding: "0.5rem", minWidth: 115 }}>Initial Status</th>
                </tr>
              </thead>
              <tbody>
                {bulkRows.map((row, idx) => {
                  const f = row.fields || {};
                  const conf = row.extraction_confidence ?? 92;
                  const warnings: string[] = row.verification_warnings || [];
                  return (
                    <tr
                      key={idx}
                      style={{
                        borderBottom: "1px solid var(--color-rule)",
                        background: row.is_crossed_out
                          ? "var(--color-danger-soft)"
                          : row.matched_profile_id
                          ? "var(--color-indigo-soft)"
                          : warnings.length > 0
                          ? "var(--color-amber-soft)"
                          : "transparent",
                        opacity: row.selected === false ? 0.5 : 1,
                      }}
                    >
                      <td style={{ padding: "0.45rem" }}>
                        <input
                          type="checkbox"
                          checked={row.selected !== false}
                          onChange={(e) => updateBulkRowMeta(idx, { selected: e.target.checked })}
                        />
                      </td>
                      <td style={{ padding: "0.45rem", minWidth: 155 }}>
                        <div style={{ display: "flex", gap: "0.25rem", flexWrap: "wrap", alignItems: "center" }}>
                          <span
                            className={`badge ${
                              conf >= 88 && warnings.length === 0
                                ? "badge-sage"
                                : conf >= 75
                                ? "badge-amber"
                                : "badge-danger"
                            }`}
                          >
                            {conf}% Conf
                          </span>
                          {row.source_modality && (
                            <span className="badge" style={{ fontSize: "0.66rem" }}>
                              {row.source_modality}
                            </span>
                          )}
                        </div>
                        {row.raw_row_notes && (
                          <div style={{ fontSize: "0.7rem", color: "var(--color-ink-2)", marginTop: "0.15rem" }}>
                            Raw: &ldquo;{row.raw_row_notes}&rdquo;
                          </div>
                        )}
                        {warnings.length > 0 && (
                          <div style={{ fontSize: "0.7rem", color: "var(--color-danger)", fontWeight: 600 }}>
                            ⚠ {warnings.join("; ")}
                          </div>
                        )}
                      </td>
                      <td style={{ padding: "0.45rem" }}>
                        <select
                          className="select"
                          style={{ padding: "0.28rem 0.45rem", fontSize: "0.78rem", minWidth: 155 }}
                          value={row.matched_profile_id ? String(row.matched_profile_id) : ""}
                          onChange={(e) =>
                            updateBulkRowMeta(idx, {
                              matched_profile_id: e.target.value ? Number(e.target.value) : null,
                              match_status: e.target.value ? "existing_match" : "new_profile",
                            })
                          }
                        >
                          <option value="">
                            {row.is_crossed_out ? "+ New (Crossed Out -> Passed)" : "+ Create New Profile"}
                          </option>
                          {allExistingProfiles.map((ep) => (
                            <option key={ep.id} value={String(ep.id)}>
                              Update Existing #{ep.id}: {ep.full_name}
                            </option>
                          ))}
                        </select>
                        {row.match_reasons?.length > 0 && (
                          <div style={{ fontSize: "0.7rem", color: "var(--color-indigo)", marginTop: "0.15rem" }}>
                            Matched: {row.match_reasons.join(", ")}
                          </div>
                        )}
                      </td>
                      <td style={{ padding: "0.45rem" }}>
                        <input
                          type="text"
                          className="input"
                          style={{ padding: "0.3rem 0.45rem", fontSize: "0.82rem" }}
                          value={f.full_name || ""}
                          onChange={(e) => updateBulkRowField(idx, "full_name", e.target.value)}
                        />
                      </td>
                      <td style={{ padding: "0.45rem" }}>
                        <input
                          type="text"
                          className="input"
                          style={{ padding: "0.3rem 0.45rem", fontSize: "0.82rem" }}
                          value={f.primary_contact_phone || ""}
                          onChange={(e) => updateBulkRowField(idx, "primary_contact_phone", e.target.value)}
                        />
                      </td>
                      <td style={{ padding: "0.45rem" }}>
                        <input
                          type="text"
                          className="input"
                          style={{ padding: "0.3rem 0.45rem", fontSize: "0.82rem" }}
                          value={f.current_city || ""}
                          onChange={(e) => updateBulkRowField(idx, "current_city", e.target.value)}
                        />
                      </td>
                      <td style={{ padding: "0.45rem" }}>
                        <input
                          type="text"
                          className="input"
                          style={{ padding: "0.3rem 0.45rem", fontSize: "0.82rem" }}
                          value={f.siblings_details || ""}
                          onChange={(e) => updateBulkRowField(idx, "siblings_details", e.target.value)}
                        />
                      </td>
                      <td style={{ padding: "0.45rem" }}>
                        <input
                          type="text"
                          className="input"
                          style={{ padding: "0.3rem 0.45rem", fontSize: "0.82rem" }}
                          value={f.occupation || ""}
                          onChange={(e) => updateBulkRowField(idx, "occupation", e.target.value)}
                        />
                      </td>
                      <td style={{ padding: "0.45rem" }}>
                        <select
                          className="select"
                          style={{ padding: "0.28rem 0.45rem", fontSize: "0.78rem" }}
                          value={f.status || "New"}
                          onChange={(e) => updateBulkRowField(idx, "status", e.target.value)}
                        >
                          <option value="New">New</option>
                          <option value="Reviewing">Reviewing</option>
                          <option value="Shortlisted">Shortlisted</option>
                          <option value="Passed">Passed (Crossed Out)</option>
                          <option value="Archived">Archived</option>
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <>
          {/* Single-Candidate AI Auto-Link & Target Profile Selector Bar */}
          <div
            className="card"
            style={{
              background: selectedTargetId ? "var(--color-sage-soft)" : "var(--color-paper-2)",
              borderColor: selectedTargetId ? "var(--color-sage)" : "var(--color-rule-strong)",
              display: "flex",
              flexDirection: "column",
              gap: "0.55rem",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
              <div>
                <div className="mono-label">
                  <Link2 size={12} style={{ verticalAlign: "middle" }} /> AI Profile Linker (Existing Profile vs. New Profile)
                </div>
                <strong>
                  {selectedTargetId
                    ? `Linked to Existing Profile #${selectedTargetId} (Updates & files will attach to this profile)`
                    : "Staged as a Brand-New Candidate Profile"}
                </strong>
                {aiAutoLinkReason && (
                  <div style={{ fontSize: "0.82rem", color: "var(--color-sage)", marginTop: "0.15rem", fontWeight: 600 }}>
                    <Sparkles size={12} style={{ verticalAlign: "middle" }} /> {aiAutoLinkReason}
                  </div>
                )}
              </div>

              <div style={{ minWidth: 280 }}>
                <select
                  className="select"
                  value={selectedTargetId ? String(selectedTargetId) : ""}
                  onChange={(e) => setSelectedTargetId(e.target.value ? Number(e.target.value) : null)}
                >
                  <option value="">+ Create as New Candidate Profile</option>
                  {allExistingProfiles.map((p) => (
                    <option key={p.id} value={String(p.id)}>
                      Link &amp; Merge into #{p.id}: {p.full_name} ({p.current_city || "City N/A"} · {p.company || p.status})
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {ext.gotra_clash_alert && (
            <div className="card" style={{ background: "var(--color-danger-soft)", borderColor: "var(--color-danger)", color: "var(--color-danger)" }}>
              <strong>
                <AlertTriangle size={16} style={{ verticalAlign: "middle" }} /> {ext.gotra_clash_alert}
              </strong>
            </div>
          )}

          {duplicates.length > 0 && (
            <div className="card" style={{ background: "var(--color-amber-soft)", borderColor: "var(--color-amber)" }}>
              <div style={{ fontWeight: 700, marginBottom: "0.4rem" }}>
                <AlertTriangle size={16} style={{ verticalAlign: "middle" }} /> Matching Existing Profiles Found in Database:
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.45rem" }}>
                {duplicates.map((d) => (
                  <div
                    key={d.profile_id}
                    style={{
                      background: "var(--color-surface)",
                      padding: "0.6rem",
                      borderRadius: "var(--radius-sm)",
                      border: "1px solid var(--color-rule)",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      flexWrap: "wrap",
                      gap: "0.5rem",
                    }}
                  >
                    <div>
                      <strong>
                        #{d.profile_id} {d.full_name}
                      </strong>{" "}
                      ({d.current_city || "City N/A"} · {d.company || "Company N/A"} · via {d.source_name || "Unknown"})
                      <div style={{ fontSize: "0.78rem", color: "var(--color-ink-2)" }}>
                        Match confidence: {Math.round(d.confidence * 100)}% — {(d.reasons || []).join(", ")}
                      </div>
                      {d.previously_passed_warning && (
                        <div className="badge badge-danger" style={{ marginTop: "0.25rem" }}>
                          {d.previously_passed_warning}
                        </div>
                      )}
                    </div>
                    <button
                      type="button"
                      className={`btn btn-sm ${selectedTargetId === d.profile_id ? "btn-primary" : ""}`}
                      onClick={() =>
                        setSelectedTargetId(selectedTargetId === d.profile_id ? null : d.profile_id)
                      }
                    >
                      <UserCheck size={14} />{" "}
                      {selectedTargetId === d.profile_id
                        ? "Linked to This Profile ✓"
                        : "Link & Merge into This Profile"}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid-2col">
            <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <h2 style={{ fontSize: "1.15rem" }}>Field-by-Field Verification</h2>
                <span className="mono-label">Uncheck any field to skip</span>
              </div>

              {editedFields.avatar_url && (
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                  <img
                    src={editedFields.avatar_url}
                    alt="Extracted portrait"
                    style={{ width: 68, height: 68, borderRadius: "var(--radius-sm)", objectFit: "cover" }}
                  />
                  <div style={{ fontSize: "0.82rem", color: "var(--color-ink-2)" }}>
                    Portrait photo automatically extracted from biodata / upload
                  </div>
                </div>
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: "0.55rem" }}>
                {Object.entries(FIELD_LABELS).map(([fieldKey, label]) => {
                  if (!(fieldKey in editedFields) || fieldKey === "avatar_url") return null;
                  const currentVal = targetProfile?.[fieldKey];
                  const prov = provenance[fieldKey];
                  return (
                    <div
                      key={fieldKey}
                      style={{
                        display: "flex",
                        alignItems: "flex-start",
                        gap: "0.55rem",
                        padding: "0.45rem",
                        background: checkedFields[fieldKey] ? "var(--color-paper-2)" : "transparent",
                        borderRadius: "var(--radius-sm)",
                        border: "1px solid var(--color-rule)",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={!!checkedFields[fieldKey]}
                        onChange={(e) =>
                          setCheckedFields((prev) => ({ ...prev, [fieldKey]: e.target.checked }))
                        }
                        style={{ marginTop: "0.4rem" }}
                      />
                      <div style={{ flex: 1 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: "0.4rem" }}>
                          <label className="mono-label">{label}</label>
                          {prov && <span className="badge">{prov}</span>}
                        </div>
                        {currentVal && currentVal !== editedFields[fieldKey] && (
                          <div style={{ fontSize: "0.75rem", color: "var(--color-ink-muted)" }}>
                            Current value: <del>{String(currentVal)}</del>
                          </div>
                        )}
                        <input
                          type="text"
                          className="input"
                          style={{ marginTop: "0.2rem", padding: "0.38rem 0.55rem", fontSize: "0.86rem" }}
                          value={String(editedFields[fieldKey] ?? "")}
                          onChange={(e) =>
                            setEditedFields((prev) => ({ ...prev, [fieldKey]: e.target.value }))
                          }
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
              <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
                <h2 style={{ fontSize: "1.15rem" }}>AI Advisor Fit &amp; Missing Questions</h2>
                {ext.fit_summary && <p style={{ margin: 0, fontSize: "0.9rem" }}>{ext.fit_summary}</p>}

                {ext.positives?.length > 0 && (
                  <div>
                    <div className="mono-label" style={{ color: "var(--color-sage)" }}>
                      Alignment Highlights
                    </div>
                    <ul style={{ margin: "0.25rem 0 0", paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
                      {ext.positives.map((p: string, i: number) => (
                        <li key={i}>{p}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {ext.concerns?.length > 0 && (
                  <div>
                    <div className="mono-label" style={{ color: "var(--color-danger)" }}>
                      Watch-outs / Concerns
                    </div>
                    <ul style={{ margin: "0.25rem 0 0", paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
                      {ext.concerns.map((c: string, i: number) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {ext.missing_questions?.length > 0 && (
                  <div>
                    <div className="mono-label" style={{ color: "var(--color-accent)" }}>
                      Questions to Clarify Next
                    </div>
                    <ul style={{ margin: "0.25rem 0 0", paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
                      {ext.missing_questions.map((q: string, i: number) => (
                        <li key={i}>{q}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="card-subtle" style={{ marginTop: "0.3rem" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "0.45rem", fontWeight: 600, fontSize: "0.86rem" }}>
                    <input
                      type="checkbox"
                      checked={createFollowUp}
                      onChange={(e) => setCreateFollowUp(e.target.checked)}
                    />
                    Create Follow-Up Reminder
                  </label>
                  {createFollowUp && (
                    <input
                      type="text"
                      className="input"
                      style={{ marginTop: "0.4rem" }}
                      value={followUpTask}
                      onChange={(e) => setFollowUpTask(e.target.value)}
                    />
                  )}
                </div>
              </div>

              {(job.raw_text || job.voice_transcript) && (
                <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                  <div className="mono-label">Segregated Input Evidence Assigned to This Person</div>
                  {job.raw_text && (
                    <div className="card-subtle" style={{ fontSize: "0.82rem", whiteSpace: "pre-wrap" }}>
                      <strong>Text / Chat Excerpt:</strong> {job.raw_text}
                    </div>
                  )}
                  {job.voice_transcript && (
                    <div className="card-subtle" style={{ fontSize: "0.82rem", whiteSpace: "pre-wrap" }}>
                      <strong>Voice Note Transcript:</strong> {job.voice_transcript}
                    </div>
                  )}
                </div>
              )}

              {Object.keys(replies).length > 0 && (
                <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
                  <h2 style={{ fontSize: "1.1rem" }}>Suggested WhatsApp Replies (claude-sonnet-4-6)</h2>
                  {Object.entries(replies).map(([key, text]) => {
                    if (!text) return null;
                    const phone =
                      editedFields.primary_contact_phone ||
                      editedFields.source_phone ||
                      editedFields.candidate_phone ||
                      "";
                    const digits = String(phone).replace(/\D/g, "").slice(-10);
                    const waUrl =
                      digits.length === 10
                        ? `https://wa.me/91${digits}?text=${encodeURIComponent(text)}`
                        : `https://wa.me/?text=${encodeURIComponent(text)}`;

                    return (
                      <div key={key} className="card-subtle" style={{ padding: "0.65rem" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.3rem" }}>
                          <span className="mono-label">{key.replace(/_/g, " ")}</span>
                          <div style={{ display: "flex", gap: "0.35rem" }}>
                            <button
                              type="button"
                              className="btn btn-sm"
                              onClick={() => copyReply(key, text)}
                            >
                              <Copy size={12} /> {copiedReplyKey === key ? "Copied ✓" : "Copy"}
                            </button>
                            <a
                              href={waUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="btn btn-primary btn-sm"
                            >
                              <ExternalLink size={12} /> 1-Tap WhatsApp
                            </a>
                          </div>
                        </div>
                        <div style={{ fontSize: "0.83rem", whiteSpace: "pre-wrap" }}>{text}</div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
};
