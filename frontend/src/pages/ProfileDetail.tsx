import React, { useEffect, useState } from "react";
import {
  AlertTriangle,
  Archive,
  ArchiveRestore,
  ArrowLeft,
  BellRing,
  Calendar,
  CheckCircle2,
  Copy,
  Edit3,
  ExternalLink,
  FileAudio,
  FileText,
  Lock,
  MessageCircle,
  MessageSquarePlus,
  PhoneCall,
  RefreshCw,
  Send,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Upload,
} from "lucide-react";
import { apiFetch, MeetingItem, Member, Profile } from "../api/client";
import { AudioRecorder } from "../components/AudioRecorder";
import { MeetingStudioModal } from "../components/MeetingStudioModal";
import { WhatsAppComposerModal } from "../components/WhatsAppComposerModal";

interface ProfileDetailProps {
  profileId: number;
  member: Member;
  onBack: () => void;
  onAddMoreMedia: (profileId: number) => void;
}

const PASS_REASONS = [
  "Location / Relocation mismatch",
  "Kundli / Gotra mismatch",
  "Career / Qualification mismatch",
  "Family expectations mismatch",
  "No mutual vibe on call/meetup",
  "Declined by prospect's family",
  "No response / Ghosted",
  "Other",
];

export const ProfileDetail: React.FC<ProfileDetailProps> = ({
  profileId,
  member,
  onBack,
  onAddMoreMedia,
}) => {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [meetings, setMeetings] = useState<MeetingItem[]>([]);
  const [editingBio, setEditingBio] = useState<boolean>(false);
  const [editDraft, setEditDraft] = useState<Record<string, any>>({});
  const [voteComment, setVoteComment] = useState<string>("");
  const [copiedClean, setCopiedClean] = useState<boolean>(false);
  const [refreshingAi, setRefreshingAi] = useState<boolean>(false);
  const [draftReplies, setDraftReplies] = useState<Record<string, string>>({});

  // Modals
  const [showWaModal, setShowWaModal] = useState<boolean>(false);
  const [activeMeetingModal, setActiveMeetingModal] = useState<MeetingItem | null | undefined>(
    undefined
  );

  // Call / Meetup Interaction Logger State
  const [logType, setLogType] = useState<string>("phone_call");
  const [logTitle, setLogTitle] = useState<string>("Phone Call with Family / Prospect");
  const [logText, setLogText] = useState<string>("");
  const [logVisibility, setLogVisibility] = useState<"shared" | "owner_only">("shared");
  const [logAudioFile, setLogAudioFile] = useState<File | null>(null);
  const [loggingCall, setLoggingCall] = useState<boolean>(false);

  // Follow-up input
  const [newFollowUpTask, setNewFollowUpTask] = useState<string>("");
  const [newFollowUpDate, setNewFollowUpDate] = useState<string>("");

  // Owner Private Notes
  const [privateNotesDraft, setPrivateNotesDraft] = useState<string>("");
  const [savingPrivate, setSavingPrivate] = useState<boolean>(false);

  const loadProfile = async () => {
    const [data, mtgRes] = await Promise.all([
      apiFetch<Profile>(`/api/profiles/${profileId}`),
      apiFetch<{ meetings: MeetingItem[] }>(`/api/meetings?profile_id=${profileId}`),
    ]);
    setProfile(data);
    setMeetings(mtgRes.meetings || []);
    setEditDraft(data);
    setPrivateNotesDraft(data.private_notes || "");
    const myVote = (data.family_votes || []).find((v) => v.member_name === member.name);
    if (myVote?.comment) setVoteComment(myVote.comment);
  };

  useEffect(() => {
    loadProfile();
  }, [profileId]);

  if (!profile) {
    return <div className="card">Loading candidate dossier #{profileId}...</div>;
  }

  const patchField = async (updates: Record<string, any>) => {
    const updated = await apiFetch<Profile>(`/api/profiles/${profileId}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    });
    setProfile((prev) => (prev ? { ...prev, ...updated } : updated));
    loadProfile();
  };

  const handleArchiveToggle = async () => {
    const archiveNow = profile.status !== "Archived";
    await apiFetch(`/api/profiles/${profileId}/archive?archive=${archiveNow}`, { method: "POST" });
    loadProfile();
  };

  const handleDeleteProfile = async () => {
    if (!window.confirm(`Permanently delete ${profile.full_name}'s dossier and all attached files?`)) {
      return;
    }
    await apiFetch(`/api/profiles/${profileId}`, { method: "DELETE" });
    onBack();
  };

  const saveBioEdits = async () => {
    await patchField(editDraft);
    setEditingBio(false);
  };

  const handleVote = async (voteVal: "shortlist" | "discuss" | "pass") => {
    await apiFetch(`/api/profiles/${profileId}/votes`, {
      method: "POST",
      body: JSON.stringify({ vote: voteVal, comment: voteComment }),
    });
    loadProfile();
  };

  const handleLogInteraction = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!logText.trim() && !logAudioFile) return;
    setLoggingCall(true);
    try {
      const fd = new FormData();
      fd.append("interaction_type", logType);
      fd.append("title", logTitle);
      fd.append("raw_text", logText);
      fd.append("visibility", logVisibility);
      fd.append("run_ai_update", "true");
      if (logAudioFile) fd.append("audio_file", logAudioFile);

      const res = await apiFetch<any>(`/api/profiles/${profileId}/interactions`, {
        method: "POST",
        body: fd,
      });
      if (res.ai_result?.draft_whatsapp_replies) {
        setDraftReplies(res.ai_result.draft_whatsapp_replies);
      }
      setLogText("");
      setLogAudioFile(null);
      await loadProfile();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setLoggingCall(false);
    }
  };

  const handleAddFollowUp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newFollowUpTask.trim()) return;
    await apiFetch(`/api/profiles/${profileId}/follow-ups`, {
      method: "POST",
      body: JSON.stringify({
        task: newFollowUpTask,
        due_date: newFollowUpDate || null,
        assigned_to: member.name,
      }),
    });
    setNewFollowUpTask("");
    setNewFollowUpDate("");
    loadProfile();
  };

  const toggleFollowUp = async (id: number, completed: boolean) => {
    await apiFetch(`/api/follow-ups/${id}?completed=${completed}`, { method: "PATCH" });
    loadProfile();
  };

  const handleRefreshAi = async () => {
    setRefreshingAi(true);
    try {
      const res = await apiFetch<any>(`/api/profiles/${profileId}/refresh-ai`, { method: "POST" });
      if (res.draft_whatsapp_replies) setDraftReplies(res.draft_whatsapp_replies);
      await loadProfile();
    } finally {
      setRefreshingAi(false);
    }
  };

  const copyCleanSummary = async () => {
    if (!profile.clean_whatsapp_summary) return;
    await navigator.clipboard.writeText(profile.clean_whatsapp_summary);
    setCopiedClean(true);
    setTimeout(() => setCopiedClean(false), 2500);
  };

  const saveOwnerPrivateNotes = async () => {
    setSavingPrivate(true);
    try {
      await patchField({ private_notes: privateNotesDraft });
    } finally {
      setSavingPrivate(false);
    }
  };

  const myVote = (profile.family_votes || []).find((v) => v.member_name === member.name)?.vote;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
      {/* Top Dossier Header */}
      <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
          <button type="button" className="btn btn-sm" onClick={onBack}>
            <ArrowLeft size={14} /> Back to Pipeline
          </button>

          <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => setShowWaModal(true)}
            >
              <MessageCircle size={13} /> 1-Tap Send Details / Follow-Up
            </button>
            <button
              type="button"
              className="btn btn-sm"
              style={{ borderColor: "var(--color-indigo)", color: "var(--color-indigo)" }}
              onClick={() => setActiveMeetingModal(null)}
            >
              <Calendar size={13} /> + Schedule Call / Upload Call Recording
            </button>
            <button type="button" className="btn btn-sm" onClick={copyCleanSummary}>
              <Copy size={13} /> {copiedClean ? "Copied Clean Summary ✓" : "Copy Clean Summary"}
            </button>
            <button type="button" className="btn btn-sm" onClick={() => onAddMoreMedia(profile.id)}>
              <Upload size={13} /> + Add PDF / Photo / Voice
            </button>
            <button
              type="button"
              className="btn btn-sm"
              data-state={refreshingAi ? "loading" : undefined}
              onClick={handleRefreshAi}
            >
              <RefreshCw size={13} /> {refreshingAi ? "Refreshing AI..." : "Re-Analyze"}
            </button>

            {member.role === "owner" && (
              <>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={handleArchiveToggle}
                  title={profile.status === "Archived" ? "Restore from Archive" : "Archive Profile (Not Needed)"}
                >
                  {profile.status === "Archived" ? (
                    <>
                      <ArchiveRestore size={13} /> Unarchive
                    </>
                  ) : (
                    <>
                      <Archive size={13} /> Archive
                    </>
                  )}
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  data-state="error"
                  onClick={handleDeleteProfile}
                  title="Delete Profile Permanently"
                >
                  <Trash2 size={13} /> Delete
                </button>
              </>
            )}
          </div>
        </div>

        {/* Candidate Identity Row */}
        <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start", flexWrap: "wrap" }}>
          {profile.avatar_url ? (
            <img
              src={profile.avatar_url}
              alt={profile.full_name}
              style={{
                width: 82,
                height: 82,
                borderRadius: "var(--radius-md)",
                objectFit: "cover",
                border: "1px solid var(--color-rule-strong)",
              }}
            />
          ) : (
            <div
              style={{
                width: 82,
                height: 82,
                borderRadius: "var(--radius-md)",
                background: "var(--color-paper-3)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: "var(--font-display)",
                fontSize: "1.7rem",
                fontWeight: 600,
                color: "var(--color-accent)",
              }}
            >
              {(profile.full_name || "?").slice(0, 2).toUpperCase()}
            </div>
          )}

          <div style={{ flex: 1, minWidth: 240 }}>
            <div className="mono-label">
              Dossier #{profile.id} · Added by {profile.created_by_member} · Referred via:{" "}
              {profile.source_name || profile.source_channel || "Direct"}
            </div>
            <h1 style={{ fontSize: "1.7rem" }}>
              {profile.full_name}
              {profile.age ? `, ${profile.age}` : ""}
            </h1>
            <div style={{ fontSize: "0.95rem", color: "var(--color-ink-2)", fontWeight: 500 }}>
              {profile.disambiguation_tag}
            </div>

            {/* Direct WhatsApp Links */}
            <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
              {profile.wa_links?.primary_contact && (
                <a
                  href={profile.wa_links.primary_contact}
                  target="_blank"
                  rel="noreferrer"
                  className="btn btn-sm"
                >
                  <ExternalLink size={12} /> WhatsApp Family ({profile.primary_contact_name || "Parent"})
                </a>
              )}
              {profile.wa_links?.candidate && (
                <a
                  href={profile.wa_links.candidate}
                  target="_blank"
                  rel="noreferrer"
                  className="btn btn-sm"
                >
                  <ExternalLink size={12} /> WhatsApp {profile.full_name.split(" ")[0]}
                </a>
              )}
              {profile.wa_links?.mediator && (
                <a
                  href={profile.wa_links.mediator}
                  target="_blank"
                  rel="noreferrer"
                  className="btn btn-sm"
                >
                  <ExternalLink size={12} /> WhatsApp Relative/Mediator ({profile.source_name})
                </a>
              )}
            </div>
          </div>

          {/* Stage + Ball in Court Controls */}
          <div style={{ display: "flex", flexDirection: "column", gap: "0.45rem", minWidth: 220 }}>
            <div>
              <label className="mono-label">Pipeline Stage</label>
              <select
                className="select"
                value={profile.status}
                onChange={(e) => patchField({ status: e.target.value })}
              >
                {[
                  "New",
                  "Reviewing",
                  "Kundli Pending",
                  "Info Needed",
                  "Talking",
                  "Meetup",
                  "Shortlisted",
                  "On Hold",
                  "Passed",
                  "Archived",
                ].map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mono-label">Whose Court Is the Ball In?</label>
              <select
                className="select"
                value={profile.ball_in_court}
                onChange={(e) => patchField({ ball_in_court: e.target.value })}
              >
                <option value="us">Ball in Our Court (Action Needed)</option>
                <option value="them">Waiting on Prospect&apos;s Family</option>
                <option value="mediator">Waiting on Relative / Mediator</option>
                <option value="closed">Closed</option>
              </select>
            </div>

            {(profile.status === "Passed" || profile.status === "Archived") && (
              <div>
                <label className="mono-label">Reason for Passing / Archiving</label>
                <select
                  className="select"
                  value={profile.pass_reason || ""}
                  onChange={(e) => patchField({ pass_reason: e.target.value })}
                >
                  <option value="">Select reason...</option>
                  {PASS_REASONS.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>

        {/* Gotra Clash Banner */}
        {profile.gotra_clash_alert && (
          <div
            className="card-subtle"
            style={{
              background: "var(--color-danger-soft)",
              borderColor: "var(--color-danger)",
              color: "var(--color-danger)",
              fontWeight: 600,
            }}
          >
            <AlertTriangle size={15} style={{ verticalAlign: "middle" }} /> {profile.gotra_clash_alert}
          </div>
        )}

        {/* Outbound Sharing Checklist ("What We Sent Them for Sister") */}
        <div
          className="card-subtle"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "0.6rem",
          }}
        >
          <span className="mono-label">
            <Send size={12} style={{ verticalAlign: "middle" }} /> Outbound Tracker (What We Sent Them):
          </span>
          <div style={{ display: "flex", gap: "0.85rem", flexWrap: "wrap", fontSize: "0.85rem" }}>
            {[
              { key: "our_biodata_sent", label: "Sister's Biodata Sent" },
              { key: "our_photos_sent", label: "Sister's Photos Sent" },
              { key: "our_kundli_sent", label: "Sister's Kundli Sent" },
              { key: "numbers_exchanged", label: "Phone Numbers Exchanged" },
            ].map((item) => (
              <label
                key={item.key}
                style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", cursor: "pointer", fontWeight: 500 }}
              >
                <input
                  type="checkbox"
                  checked={(profile as any)[item.key] === 1}
                  onChange={(e) => patchField({ [item.key]: e.target.checked ? 1 : 0 })}
                />
                {item.label}
              </label>
            ))}
          </div>
        </div>
      </div>

      {/* Family Alignment Votes Bar */}
      <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
          <div>
            <div className="mono-label">Family Alignment &amp; Decision Bar</div>
            <h2 style={{ fontSize: "1.12rem" }}>Cast Your Vote as {member.name}</h2>
          </div>

          <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
            <button
              type="button"
              className={`btn btn-sm ${myVote === "shortlist" ? "btn-primary" : ""}`}
              onClick={() => handleVote("shortlist")}
            >
              <ThumbsUp size={14} /> Shortlist
            </button>
            <button
              type="button"
              className={`btn btn-sm ${myVote === "discuss" ? "btn-primary" : ""}`}
              onClick={() => handleVote("discuss")}
            >
              Discuss / Need Info
            </button>
            <button
              type="button"
              className={`btn btn-sm ${myVote === "pass" ? "btn-primary" : ""}`}
              onClick={() => handleVote("pass")}
            >
              <ThumbsDown size={14} /> Pass
            </button>
          </div>
        </div>

        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <input
            type="text"
            className="input"
            style={{ flex: 1 }}
            placeholder={`Optional note with ${member.name}'s vote (visible to family)...`}
            value={voteComment}
            onChange={(e) => setVoteComment(e.target.value)}
          />
          {myVote && (
            <button type="button" className="btn btn-sm" onClick={() => handleVote(myVote)}>
              Save Note
            </button>
          )}
        </div>

        {(profile.family_votes || []).length > 0 && (
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {(profile.family_votes || []).map((v) => (
              <div key={v.id} className="badge" style={{ padding: "0.3rem 0.65rem" }}>
                <strong>{v.member_name}:</strong> {v.vote.toUpperCase()}
                {v.comment ? ` — "${v.comment}"` : ""}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Two-Column Body */}
      <div className="grid-2col">
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
          {/* Dedicated Kundli / Horoscope & Gotra Gate Card */}
          <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div className="mono-label">Horoscope &amp; Lineage Gate</div>
                <h2 style={{ fontSize: "1.15rem" }}>Kundli, Birth Details &amp; Gotra</h2>
              </div>
              <select
                className="select"
                style={{ width: "auto" }}
                value={profile.kundli_status || "Not Checked"}
                onChange={(e) => patchField({ kundli_status: e.target.value })}
              >
                <option value="Not Checked">Not Checked</option>
                <option value="At Panditji">Sent to Panditji</option>
                <option value="Matched">Matched ✓</option>
                <option value="Concern">Dosha / Concern</option>
                <option value="Not Needed">Not Required</option>
              </select>
            </div>

            <div className="grid-2col" style={{ fontSize: "0.86rem" }}>
              <div>
                <span className="mono-label">Date of Birth:</span>{" "}
                <strong>{profile.dob || "Not mentioned"}</strong>
              </div>
              <div>
                <span className="mono-label">Time of Birth:</span>{" "}
                <strong>{profile.time_of_birth || "Ask family"}</strong>
              </div>
              <div>
                <span className="mono-label">Place of Birth:</span>{" "}
                <strong>{profile.place_of_birth || "Ask family"}</strong>
              </div>
              <div>
                <span className="mono-label">Gotra:</span>{" "}
                <strong>{profile.gotra || "Not mentioned"}</strong>
              </div>
              <div>
                <span className="mono-label">Manglik:</span>{" "}
                <strong>{profile.manglik || "Unknown"}</strong>
              </div>
              <div>
                <span className="mono-label">Guna Score:</span>{" "}
                <input
                  type="text"
                  className="input"
                  style={{ display: "inline-block", width: 110, padding: "0.2rem 0.45rem", fontSize: "0.82rem" }}
                  placeholder="e.g. 28/36"
                  value={profile.kundli_gunas || ""}
                  onChange={(e) => patchField({ kundli_gunas: e.target.value })}
                />
              </div>
            </div>
          </div>

          {/* Candidate Bio, Career & Family Details */}
          <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h2 style={{ fontSize: "1.15rem" }}>Structured Candidate Dossier</h2>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => (editingBio ? saveBioEdits() : setEditingBio(true))}
              >
                <Edit3 size={13} /> {editingBio ? "Save Changes" : "Edit Fields"}
              </button>
            </div>

            {editingBio ? (
              <div className="grid-2col">
                {[
                  ["full_name", "Full Name"],
                  ["age", "Age"],
                  ["height", "Height"],
                  ["diet", "Diet"],
                  ["education", "Education"],
                  ["college", "College"],
                  ["occupation", "Occupation"],
                  ["company", "Company"],
                  ["annual_ctc", "Package (LPA)"],
                  ["current_city", "Current City"],
                  ["hometown", "Hometown"],
                  ["relocation_openness", "Relocation Openness"],
                  ["father_details", "Father Details"],
                  ["mother_details", "Mother Details"],
                  ["siblings_details", "Siblings Details"],
                  ["caste_community", "Community"],
                  ["gotra", "Gotra"],
                  ["source_name", "Referred By (Relative / Mediator)"],
                  ["primary_contact_name", "Family Contact Name"],
                  ["primary_contact_phone", "Family Contact Phone"],
                  ["candidate_phone", "Candidate Phone"],
                ].map(([k, label]) => (
                  <div key={k}>
                    <label className="mono-label">{label}</label>
                    <input
                      type="text"
                      className="input"
                      value={String(editDraft[k] ?? "")}
                      onChange={(e) => setEditDraft((prev) => ({ ...prev, [k]: e.target.value }))}
                    />
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.55rem", fontSize: "0.88rem" }}>
                <div>
                  <span className="mono-label">Height &amp; Lifestyle:</span>{" "}
                  {[profile.height, profile.diet, profile.smoking_drinking, profile.marital_status]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </div>
                <div>
                  <span className="mono-label">Education:</span>{" "}
                  {[profile.education, profile.college].filter(Boolean).join(" — ") || "—"}
                </div>
                <div>
                  <span className="mono-label">Career &amp; Package:</span>{" "}
                  {[profile.occupation, profile.company, profile.annual_ctc, profile.work_mode]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </div>
                <div>
                  <span className="mono-label">Location &amp; Relocation:</span>{" "}
                  Current: {profile.current_city || "—"} | Hometown: {profile.hometown || "—"} | Relocation:{" "}
                  {profile.relocation_openness || "—"}
                </div>
                <div>
                  <span className="mono-label">Father:</span> {profile.father_details || "—"}
                </div>
                <div>
                  <span className="mono-label">Mother:</span> {profile.mother_details || "—"}
                </div>
                <div>
                  <span className="mono-label">Siblings:</span> {profile.siblings_details || "—"}
                </div>
                <div>
                  <span className="mono-label">Contacts:</span>{" "}
                  {profile.primary_contact_name || "Parent"} ({profile.primary_contact_phone || "No phone"}) |
                  Candidate: {profile.candidate_phone || "No direct phone"}
                </div>
              </div>
            )}
          </div>

          {/* OWNER-ONLY Private Notes Card (Hidden from Family Sessions!) */}
          {member.role === "owner" && (
            <div
              className="card"
              style={{
                borderColor: "var(--color-indigo)",
                background: "var(--color-indigo-soft)",
                display: "flex",
                flexDirection: "column",
                gap: "0.5rem",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div className="mono-label" style={{ color: "var(--color-indigo)" }}>
                    <Lock size={12} style={{ verticalAlign: "middle" }} /> Owner-Only Private Vault (Hidden from Family Logins)
                  </div>
                  <h3 style={{ fontSize: "1.02rem" }}>Saurabh&apos;s Personal Background Check &amp; Notes</h3>
                </div>
                <button
                  type="button"
                  className="btn btn-sm"
                  data-state={savingPrivate ? "loading" : undefined}
                  onClick={saveOwnerPrivateNotes}
                >
                  Save Private Note
                </button>
              </div>
              <textarea
                className="textarea"
                rows={3}
                placeholder="Write candid personal observations (never visible on family logins)..."
                value={privateNotesDraft}
                onChange={(e) => setPrivateNotesDraft(e.target.value)}
              />
            </div>
          )}

          {/* Media Assets Vault (Biodata PDFs, Photos, Voice Notes, Call Recordings) */}
          {(profile.media_assets || []).length > 0 && (
            <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.55rem" }}>
              <h2 style={{ fontSize: "1.1rem" }}>Uploaded Biodata PDFs, Photos &amp; Call Recordings</h2>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.45rem" }}>
                {(profile.media_assets || []).map((a) => (
                  <div
                    key={a.id}
                    className="card-subtle"
                    style={{
                      padding: "0.5rem 0.65rem",
                      display: "flex",
                      flexDirection: "column",
                      gap: "0.35rem",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontSize: "0.84rem", fontWeight: 600 }}>
                        <FileText size={13} style={{ verticalAlign: "middle" }} /> {a.file_name}{" "}
                        <span className="mono-label">({a.asset_type})</span>
                      </span>
                      <a
                        href={a.url_path}
                        target="_blank"
                        rel="noreferrer"
                        className="btn btn-sm"
                      >
                        Open File
                      </a>
                    </div>
                    {a.asset_type === "voice_note" && (
                      <audio controls src={a.url_path} style={{ width: "100%", height: 34 }} />
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Meetings & Call Recordings + Pre-Call Cheat Sheet + Call Logger + Follow-Ups + Timeline */}
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
          {/* 3-Stage Meetings, 2-Phone Reminders & Call Recordings Card */}
          <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.4rem" }}>
              <div>
                <div className="mono-label">
                  <Calendar size={12} style={{ verticalAlign: "middle" }} /> 3-Stage Meeting &amp; Call Recording Hub
                </div>
                <h2 style={{ fontSize: "1.15rem" }}>Scheduled Calls, 2-Phone Alerts &amp; Recordings</h2>
              </div>
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={() => setActiveMeetingModal(null)}
              >
                + Schedule Call / Upload Recording
              </button>
            </div>

            {meetings.length === 0 ? (
              <div style={{ fontSize: "0.84rem", color: "var(--color-ink-2)" }}>
                No calls or meetings scheduled yet. Tap <strong>+ Schedule Call / Upload Recording</strong> to propose
                slots, arm 2-phone reminders, or upload a completed call recording.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                {meetings.map((m) => (
                  <div key={m.id} className="card-subtle" style={{ padding: "0.6rem" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.5rem", flexWrap: "wrap" }}>
                      <div>
                        <strong>{m.title}</strong>{" "}
                        <span
                          className={`badge ${
                            m.stage === "completed"
                              ? "badge-sage"
                              : m.stage === "scheduled"
                              ? "badge-indigo"
                              : "badge-amber"
                          }`}
                        >
                          {m.stage.toUpperCase()}
                        </span>
                        <div style={{ fontSize: "0.8rem", color: "var(--color-ink-2)", marginTop: "0.15rem" }}>
                          {m.stage === "proposing"
                            ? `Proposed Slots: ${m.proposed_slots_text || "TBD"}`
                            : `When: ${(m.scheduled_at || "").replace("T", " at ")}`}
                          {" · "}Participants: {m.participants}
                        </div>
                      </div>

                      <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                        {m.stage !== "completed" && (
                          <button
                            type="button"
                            className="btn btn-sm btn-primary"
                            onClick={() => setActiveMeetingModal({ ...m, stage: "completed" })}
                          >
                            <FileAudio size={12} /> Upload Call Recording / Done
                          </button>
                        )}
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => setActiveMeetingModal(m)}
                        >
                          Edit / Alerts
                        </button>
                      </div>
                    </div>

                    {m.call_recording_url && (
                      <div style={{ marginTop: "0.45rem" }}>
                        <div className="mono-label">Call Recording Audio</div>
                        <audio controls src={m.call_recording_url} style={{ width: "100%", height: 34, marginTop: "0.2rem" }} />
                      </div>
                    )}
                    {m.ai_call_summary && (
                      <div style={{ marginTop: "0.35rem", fontSize: "0.82rem" }}>
                        <strong>AI Call Takeaways:</strong> {m.ai_call_summary}
                      </div>
                    )}
                    {m.call_transcript && (
                      <div
                        style={{
                          marginTop: "0.35rem",
                          padding: "0.4rem",
                          background: "var(--color-surface)",
                          borderRadius: "var(--radius-sm)",
                          fontSize: "0.78rem",
                          whiteSpace: "pre-wrap",
                        }}
                      >
                        <strong>Call Recording Transcript:</strong> {m.call_transcript}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Pre-Call Cheat Sheet & AI Fit Summary */}
          <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div className="mono-label">AI Fit &amp; Pre-Call Cheat Sheet</div>
                <h2 style={{ fontSize: "1.15rem" }}>Conversation Prep &amp; Open Questions</h2>
              </div>
              {typeof profile.ai_fit_score === "number" && (
                <span className="badge badge-sage">Fit {profile.ai_fit_score}%</span>
              )}
            </div>

            {profile.fit_summary && <p style={{ margin: 0, fontSize: "0.88rem" }}>{profile.fit_summary}</p>}

            {profile.pre_call_brief && (
              <div className="card-subtle" style={{ fontSize: "0.84rem", whiteSpace: "pre-wrap" }}>
                <div className="mono-label" style={{ marginBottom: "0.25rem" }}>
                  <PhoneCall size={12} style={{ verticalAlign: "middle" }} /> Pre-Call Brief
                </div>
                {profile.pre_call_brief}
              </div>
            )}

            {profile.missing_questions?.length > 0 && (
              <div>
                <div className="mono-label" style={{ color: "var(--color-accent)" }}>
                  Questions to Ask on Next Call / WhatsApp
                </div>
                <ul style={{ margin: "0.25rem 0 0", paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
                  {profile.missing_questions.map((q, idx) => (
                    <li key={idx}>{q}</li>
                  ))}
                </ul>
              </div>
            )}

            {Object.keys(draftReplies).length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
                <div className="mono-label">Fresh AI WhatsApp Drafts</div>
                {Object.entries(draftReplies).map(([k, txt]) => (
                  <div key={k} className="card-subtle" style={{ fontSize: "0.8rem" }}>
                    <strong>{k.replace(/_/g, " ")}:</strong> {txt}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Log Quick Phone Call / Meetup / Hinglish Voice Recap */}
          <form onSubmit={handleLogInteraction} className="card" style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
            <div className="mono-label">Quick Call &amp; Voice Note Logger</div>
            <h2 style={{ fontSize: "1.12rem" }}>Add Quick Note or Voice Recording</h2>

            <div className="grid-2col">
              <select className="select" value={logType} onChange={(e) => setLogType(e.target.value)}>
                <option value="phone_call">Phone Call Recap</option>
                <option value="meetup">In-Person Meetup Feedback</option>
                <option value="voice_note">Voice Note / Call Recording</option>
                <option value="note">Family Discussion Note</option>
              </select>

              {member.role === "owner" && (
                <select
                  className="select"
                  value={logVisibility}
                  onChange={(e) => setLogVisibility(e.target.value as "shared" | "owner_only")}
                >
                  <option value="shared">Visible to Family</option>
                  <option value="owner_only">Owner-Only Private</option>
                </select>
              )}
            </div>

            <input
              type="text"
              className="input"
              placeholder="Title e.g. Spoke to prospect's family / Coffee meetup"
              value={logTitle}
              onChange={(e) => setLogTitle(e.target.value)}
            />

            <textarea
              className="textarea"
              rows={3}
              placeholder="Type call outcome (e.g. 'Interested, need kundli first, prefers Gurgaon/Bangalore')..."
              value={logText}
              onChange={(e) => setLogText(e.target.value)}
            />

            <AudioRecorder onAudioReady={(file) => setLogAudioFile(file)} />

            <button
              type="submit"
              className="btn btn-primary"
              disabled={loggingCall}
              data-state={loggingCall ? "loading" : undefined}
            >
              <Sparkles size={15} />{" "}
              {loggingCall ? "Updating Profile with AI..." : "Save & Auto-Update Profile via AI"}
            </button>
          </form>

          {/* Follow-Up Reminders */}
          <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
            <h2 style={{ fontSize: "1.1rem" }}>Follow-Up Tasks</h2>
            <form onSubmit={handleAddFollowUp} style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
              <input
                type="text"
                className="input"
                style={{ flex: "1 1 180px" }}
                placeholder="Add follow-up reminder..."
                value={newFollowUpTask}
                onChange={(e) => setNewFollowUpTask(e.target.value)}
              />
              <input
                type="date"
                className="input"
                style={{ width: 145 }}
                value={newFollowUpDate}
                onChange={(e) => setNewFollowUpDate(e.target.value)}
              />
              <button type="submit" className="btn btn-sm btn-primary">
                + Add
              </button>
            </form>

            <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
              {(profile.follow_ups || []).map((fu) => (
                <div
                  key={fu.id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "0.4rem 0.55rem",
                    background: fu.completed ? "var(--color-paper-2)" : "var(--color-surface)",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--color-rule)",
                    opacity: fu.completed ? 0.65 : 1,
                    fontSize: "0.84rem",
                  }}
                >
                  <div>
                    <span style={{ textDecoration: fu.completed ? "line-through" : "none" }}>
                      {fu.task}
                    </span>{" "}
                    <span className="mono-label">
                      ({fu.assigned_to} · {fu.due_date || "No date"})
                    </span>
                  </div>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => toggleFollowUp(fu.id, fu.completed === 0)}
                  >
                    <CheckCircle2 size={13} /> {fu.completed ? "Reopen" : "Done"}
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Chronological Interaction Timeline */}
          <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
            <h2 style={{ fontSize: "1.1rem" }}>Interaction &amp; Import Timeline</h2>
            {(profile.interactions || []).length === 0 ? (
              <div style={{ fontSize: "0.84rem", color: "var(--color-ink-muted)" }}>
                No interactions logged yet.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.55rem" }}>
                {(profile.interactions || []).map((item) => (
                  <div key={item.id} className="card-subtle" style={{ padding: "0.65rem" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "0.4rem", flexWrap: "wrap" }}>
                      <strong style={{ fontSize: "0.88rem" }}>
                        <MessageSquarePlus size={13} style={{ verticalAlign: "middle" }} /> {item.title}
                      </strong>
                      <span className="mono-label">
                        {item.created_by_member} · {item.occurred_at.slice(0, 10)}
                        {item.visibility === "owner_only" ? " · [PRIVATE]" : ""}
                      </span>
                    </div>
                    {item.summary && (
                      <p style={{ margin: "0.3rem 0 0", fontSize: "0.84rem" }}>{item.summary}</p>
                    )}
                    {item.transcript && (
                      <div
                        style={{
                          marginTop: "0.35rem",
                          padding: "0.4rem",
                          background: "var(--color-surface)",
                          borderRadius: "var(--radius-sm)",
                          fontSize: "0.78rem",
                        }}
                      >
                        <strong>Voice / Call Transcript:</strong> {item.transcript}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 1-Tap WhatsApp Outreach & Granular Follow-Up Modal */}
      {showWaModal && (
        <WhatsAppComposerModal
          profileId={profile.id}
          onClose={() => setShowWaModal(false)}
          onSentAndLogged={() => loadProfile()}
        />
      )}

      {/* 3-Stage Meeting & Call Recording Studio Modal */}
      {activeMeetingModal !== undefined && (
        <MeetingStudioModal
          profileId={profile.id}
          candidateName={profile.full_name}
          existingMeeting={activeMeetingModal}
          defaultPreCallNotes={profile.pre_call_brief || ""}
          onClose={() => setActiveMeetingModal(undefined)}
          onSaved={() => loadProfile()}
        />
      )}
    </div>
  );
};
