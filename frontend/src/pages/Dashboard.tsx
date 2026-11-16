import React, { useEffect, useState } from "react";
import {
  AlertTriangle,
  Archive,
  ArchiveRestore,
  BellRing,
  Calendar,
  CheckCircle2,
  Copy,
  FileAudio,
  FilePlus2,
  GitCompare,
  MessageCircle,
  Search,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Users,
} from "lucide-react";
import { apiFetch, FollowUpItem, MeetingItem, Member, Profile } from "../api/client";
import { MeetingStudioModal } from "../components/MeetingStudioModal";
import { WhatsAppComposerModal } from "../components/WhatsAppComposerModal";

interface DashboardProps {
  member: Member;
  onOpenProfile: (id: number) => void;
  onOpenImport: () => void;
  onOpenReviewJob: (jobId: number) => void;
  onOpenCompare: (ids: number[]) => void;
}

const PIPELINE_STAGES = [
  "ACTIVE",
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
  "ALL",
];

export const Dashboard: React.FC<DashboardProps> = ({
  member,
  onOpenProfile,
  onOpenImport,
  onOpenReviewJob,
  onOpenCompare,
}) => {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [pendingJobs, setPendingJobs] = useState<any[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("ACTIVE");
  const [ballFilter, setBallFilter] = useState<string>("ALL");
  const [mediatorFilter, setMediatorFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [compareIds, setCompareIds] = useState<number[]>([]);
  const [copiedMediatorMsg, setCopiedMediatorMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  // Modals for 1-Tap WhatsApp Outreach & Meeting/Call Recording Studio
  const [waModalProfileId, setWaModalProfileId] = useState<number | null | undefined>(undefined);
  const [meetingModalState, setMeetingModalState] = useState<{
    profileId: number;
    candidateName: string;
    meeting?: MeetingItem | null;
  } | null>(null);

  const loadData = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set("status", statusFilter);
      if (ballFilter !== "ALL") params.set("ball_in_court", ballFilter);
      if (mediatorFilter !== "ALL") params.set("source_name", mediatorFilter);
      if (searchQuery.trim()) params.set("q", searchQuery.trim());

      const [profRes, statsRes, jobsRes] = await Promise.all([
        apiFetch<{ profiles: Profile[] }>(`/api/profiles?${params.toString()}`),
        apiFetch<any>("/api/profiles/summary-stats"),
        apiFetch<{ jobs: any[] }>("/api/imports?status=pending_review"),
      ]);
      setProfiles(profRes.profiles || []);
      setStats(statsRes);
      setPendingJobs(jobsRes.jobs || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [statusFilter, ballFilter, mediatorFilter, searchQuery]);

  const toggleFollowUpDone = async (fu: FollowUpItem) => {
    await apiFetch(`/api/follow-ups/${fu.id}?completed=true`, { method: "PATCH" });
    loadData();
  };

  const toggleCompareId = (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    setCompareIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : prev.length < 4 ? [...prev, id] : prev
    );
  };

  const handleArchiveToggle = async (p: Profile, e: React.MouseEvent) => {
    e.stopPropagation();
    const archiveNow = p.status !== "Archived";
    await apiFetch(`/api/profiles/${p.id}/archive?archive=${archiveNow}`, { method: "POST" });
    loadData();
  };

  const handleDeleteProfile = async (p: Profile, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(`Permanently delete ${p.full_name}'s profile and all its files?`)) return;
    await apiFetch(`/api/profiles/${p.id}`, { method: "DELETE" });
    loadData();
  };

  const handleSendMeetingAlertNow = async (meetingId: number) => {
    const res = await apiFetch<any>(`/api/meetings/${meetingId}/send-reminder`, { method: "POST" });
    alert(`Reminder sent via: ${(res.sent_channels || []).join(", ")}`);
  };

  const copyMediatorUpdate = async (sourceName: string) => {
    try {
      const res = await apiFetch<{ whatsapp_report_text: string }>(
        `/api/profiles/mediator-report/${encodeURIComponent(sourceName)}`
      );
      await navigator.clipboard.writeText(res.whatsapp_report_text);
      setCopiedMediatorMsg(`Copied WhatsApp update for ${sourceName}!`);
      setTimeout(() => setCopiedMediatorMsg(null), 3500);
    } catch (err: any) {
      alert(err.message);
    }
  };

  const ballBadge = (ball: string) => {
    if (ball === "us") return <span className="badge badge-accent">Ball: Our Court</span>;
    if (ball === "them") return <span className="badge badge-indigo">Waiting on Them</span>;
    if (ball === "mediator") return <span className="badge badge-amber">Via Relative/Mediator</span>;
    return <span className="badge">Closed</span>;
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
      {/* Staged AI Imports Waiting for Review */}
      {pendingJobs.length > 0 && (
        <div
          className="card"
          style={{
            background: "var(--color-accent-soft)",
            borderColor: "var(--color-accent)",
            display: "flex",
            flexDirection: "column",
            gap: "0.55rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <Sparkles size={18} color="var(--color-accent)" />
              <strong>{pendingJobs.length} AI Extraction(s) Ready for Review</strong>
            </div>
            <span className="mono-label">Verify fields before saving</span>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {pendingJobs.map((j) => {
              const name = j.extracted?.extracted_fields?.full_name || "New Candidate";
              return (
                <button
                  key={j.id}
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => onOpenReviewJob(j.id)}
                >
                  Review #{j.id}: {name}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Top Action & Stats Bar */}
      <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.75rem" }}>
          <div>
            <div className="mono-label">
              Sister&apos;s Rishta Ledger · Logged in as {member.name} ({member.role})
            </div>
            <h1 style={{ fontSize: "1.55rem" }}>Candidate Pipeline, Meetings &amp; Follow-Ups</h1>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {compareIds.length >= 2 && (
              <button
                type="button"
                className="btn"
                style={{ borderColor: "var(--color-indigo)", color: "var(--color-indigo)" }}
                onClick={() => onOpenCompare(compareIds)}
              >
                <GitCompare size={16} /> Compare ({compareIds.length})
              </button>
            )}
            <button
              type="button"
              className="btn"
              onClick={() => setWaModalProfileId(null)}
              title="1-Tap send Sister's Biodata or Follow-Up to any relative or phone number"
            >
              <MessageCircle size={16} /> 1-Tap Send Details / Follow-Up
            </button>
            <button type="button" className="btn btn-primary" onClick={onOpenImport}>
              <FilePlus2 size={16} /> + Quick Import Rishta
            </button>
          </div>
        </div>

        {/* Upcoming Scheduled Calls & Meetings Banner */}
        {stats?.upcoming_meetings?.length > 0 && (
          <div
            className="card-subtle"
            style={{
              background: "var(--color-indigo-soft)",
              borderColor: "var(--color-indigo)",
              padding: "0.75rem",
            }}
          >
            <div className="mono-label" style={{ color: "var(--color-indigo)", marginBottom: "0.4rem" }}>
              <Calendar size={12} style={{ verticalAlign: "middle" }} /> Scheduled Calls &amp; Meetings (2-Phone Reminders Armed)
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
              {stats.upcoming_meetings.map((m: MeetingItem) => (
                <div
                  key={m.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    flexWrap: "wrap",
                    gap: "0.5rem",
                    background: "var(--color-surface)",
                    padding: "0.45rem 0.65rem",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--color-rule)",
                    fontSize: "0.85rem",
                  }}
                >
                  <div style={{ cursor: "pointer" }} onClick={() => onOpenProfile(m.profile_id)}>
                    <strong>{m.candidate_name}</strong> — {m.meeting_type}{" "}
                    <span className="badge badge-indigo">
                      {m.stage === "scheduled"
                        ? (m.scheduled_at || "").replace("T", " at ")
                        : `Proposing: ${m.proposed_slots_text}`}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => handleSendMeetingAlertNow(m.id)}
                    >
                      <BellRing size={12} /> Alert 2 Phones Now
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      onClick={() =>
                        setMeetingModalState({
                          profileId: m.profile_id,
                          candidateName: m.candidate_name || "Candidate",
                          meeting: { ...m, stage: "completed" },
                        })
                      }
                    >
                      <FileAudio size={12} /> Done / Upload Call Recording
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Ball-in-Court Summary Pills */}
        {stats && (
          <div className="filter-strip">
            <button
              type="button"
              className={`btn btn-sm ${ballFilter === "ALL" ? "btn-primary" : ""}`}
              onClick={() => setBallFilter("ALL")}
            >
              All Active
            </button>
            <button
              type="button"
              className={`btn btn-sm ${ballFilter === "us" ? "btn-primary" : ""}`}
              onClick={() => setBallFilter(ballFilter === "us" ? "ALL" : "us")}
            >
              Action Needed by Us ({stats.by_ball_in_court?.us || 0})
            </button>
            <button
              type="button"
              className={`btn btn-sm ${ballFilter === "them" ? "btn-primary" : ""}`}
              onClick={() => setBallFilter(ballFilter === "them" ? "ALL" : "them")}
            >
              Waiting on Prospect Family ({stats.by_ball_in_court?.them || 0})
            </button>
            <button
              type="button"
              className={`btn btn-sm ${ballFilter === "mediator" ? "btn-primary" : ""}`}
              onClick={() => setBallFilter(ballFilter === "mediator" ? "ALL" : "mediator")}
            >
              Waiting on Relative / Mediator ({stats.by_ball_in_court?.mediator || 0})
            </button>
          </div>
        )}

        {/* Open Follow-Ups Strip */}
        {stats?.open_follow_ups?.length > 0 && (
          <div className="card-subtle" style={{ padding: "0.7rem" }}>
            <div className="mono-label" style={{ marginBottom: "0.4rem" }}>
              Pending Family Follow-Ups ({stats.open_follow_ups.length})
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
              {stats.open_follow_ups.slice(0, 4).map((fu: FollowUpItem) => (
                <div
                  key={fu.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "0.5rem",
                    fontSize: "0.85rem",
                    padding: "0.3rem 0.45rem",
                    background: "var(--color-surface)",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--color-rule)",
                  }}
                >
                  <div
                    style={{ cursor: "pointer", flex: 1 }}
                    onClick={() => onOpenProfile(fu.profile_id)}
                  >
                    <strong>{fu.full_name}</strong>: {fu.task}{" "}
                    <span className="mono-label">
                      ({fu.assigned_to} · Due {fu.due_date || "Soon"})
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: "0.35rem" }}>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => setWaModalProfileId(fu.profile_id)}
                    >
                      <MessageCircle size={13} /> 1-Tap Follow-Up
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => toggleFollowUpDone(fu)}
                    >
                      <CheckCircle2 size={14} /> Done
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Relatives / Mediators Filter & One-Tap Status Report */}
        {stats?.mediators?.length > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", flexWrap: "wrap" }}>
            <span className="mono-label">
              <Users size={12} style={{ verticalAlign: "middle" }} /> Relatives / Mediators:
            </span>
            <button
              type="button"
              className={`btn btn-sm ${mediatorFilter === "ALL" ? "btn-primary" : ""}`}
              onClick={() => setMediatorFilter("ALL")}
            >
              All Sources
            </button>
            {stats.mediators.map((m: any) => (
              <div key={m.source_name} style={{ display: "inline-flex", gap: "0.2rem" }}>
                <button
                  type="button"
                  className={`btn btn-sm ${mediatorFilter === m.source_name ? "btn-primary" : ""}`}
                  onClick={() =>
                    setMediatorFilter(mediatorFilter === m.source_name ? "ALL" : m.source_name)
                  }
                >
                  {m.source_name} ({m.total})
                </button>
                {mediatorFilter === m.source_name && (
                  <button
                    type="button"
                    className="btn btn-sm"
                    title="Copy polite WhatsApp status update for this relative/mediator"
                    onClick={() => copyMediatorUpdate(m.source_name)}
                  >
                    <Copy size={13} /> Copy Update for {m.source_name}
                  </button>
                )}
              </div>
            ))}
            {copiedMediatorMsg && <span className="badge badge-sage">{copiedMediatorMsg}</span>}
          </div>
        )}

        {/* Search + Stage Filter Strip */}
        <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", alignItems: "center" }}>
          <div style={{ position: "relative", flex: "1 1 240px" }}>
            <Search
              size={15}
              style={{
                position: "absolute",
                left: "0.7rem",
                top: "50%",
                transform: "translateY(-50%)",
                color: "var(--color-ink-muted)",
              }}
            />
            <input
              type="search"
              className="input"
              style={{ paddingLeft: "2.1rem" }}
              placeholder="Search name, city, company, CA/MBA/IIT, gotra, or relative..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>

        <div className="filter-strip">
          {PIPELINE_STAGES.map((st) => {
            const count =
              st === "ACTIVE" || st === "ALL" ? null : stats?.by_status?.[st] || 0;
            return (
              <button
                key={st}
                type="button"
                className={`btn btn-sm ${statusFilter === st ? "btn-primary" : ""}`}
                onClick={() => setStatusFilter(st)}
              >
                {st === "ACTIVE" ? "Active Pipeline" : st === "ALL" ? "All Profiles" : st}
                {count !== null ? ` (${count})` : ""}
              </button>
            );
          })}
        </div>
      </div>

      {/* Candidate Cards Grid */}
      {loading ? (
        <div className="card" style={{ textAlign: "center", padding: "2.5rem" }}>
          Loading profiles...
        </div>
      ) : profiles.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: "2.5rem" }}>
          <h3 style={{ marginBottom: "0.5rem" }}>No candidate profiles in this view</h3>
          <p style={{ color: "var(--color-ink-2)", marginBottom: "1rem" }}>
            Paste a WhatsApp message, upload a biodata PDF/screenshot, or drop a Hinglish voice note to create a dossier.
          </p>
          <button type="button" className="btn btn-primary" onClick={onOpenImport}>
            <FilePlus2 size={16} /> Import Rishta
          </button>
        </div>
      ) : (
        <div className="grid-profiles">
          {profiles.map((p) => {
            const isSelectedForCompare = compareIds.includes(p.id);
            const nextFu = p.open_follow_ups?.[0];
            return (
              <div
                key={p.id}
                className="card"
                onClick={() => onOpenProfile(p.id)}
                style={{
                  cursor: "pointer",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  gap: "0.75rem",
                  borderColor: isSelectedForCompare ? "var(--color-indigo)" : undefined,
                  opacity: p.status === "Archived" ? 0.78 : 1,
                }}
              >
                <div style={{ display: "flex", flexDirection: "column", gap: "0.55rem" }}>
                  {/* Card Header: Avatar + Name + Fit Score */}
                  <div style={{ display: "flex", gap: "0.75rem", alignItems: "flex-start" }}>
                    {p.avatar_url ? (
                      <img
                        src={p.avatar_url}
                        alt={p.full_name}
                        style={{
                          width: 54,
                          height: 54,
                          borderRadius: "var(--radius-sm)",
                          objectFit: "cover",
                          border: "1px solid var(--color-rule-strong)",
                          flexShrink: 0,
                        }}
                      />
                    ) : (
                      <div
                        style={{
                          width: 54,
                          height: 54,
                          borderRadius: "var(--radius-sm)",
                          background: "var(--color-paper-3)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontFamily: "var(--font-display)",
                          fontSize: "1.2rem",
                          fontWeight: 600,
                          color: "var(--color-accent)",
                          flexShrink: 0,
                        }}
                      >
                        {(p.full_name || "?").slice(0, 2).toUpperCase()}
                      </div>
                    )}

                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.35rem", alignItems: "flex-start" }}>
                        <h3 style={{ fontSize: "1.12rem" }}>
                          {p.full_name}
                          {p.age ? `, ${p.age}` : ""}
                        </h3>
                        {typeof p.ai_fit_score === "number" && (
                          <span
                            className={`badge ${
                              p.ai_fit_score >= 80
                                ? "badge-sage"
                                : p.ai_fit_score >= 65
                                ? "badge-amber"
                                : "badge-danger"
                            }`}
                          >
                            Fit {p.ai_fit_score}%
                          </span>
                        )}
                      </div>
                      <div
                        style={{
                          fontSize: "0.82rem",
                          color: "var(--color-ink-2)",
                          fontWeight: 500,
                          marginTop: "0.15rem",
                        }}
                      >
                        {p.disambiguation_tag || "Profile in review"}
                      </div>
                    </div>
                  </div>

                  {/* Status + Ball in Court + Kundli Pills */}
                  <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                    <span className="badge badge-accent">{p.status}</span>
                    {ballBadge(p.ball_in_court)}
                    {p.kundli_status && p.kundli_status !== "Not Checked" && (
                      <span className="badge badge-sage">Kundli: {p.kundli_status}</span>
                    )}
                    {p.annual_ctc && <span className="badge">{p.annual_ctc}</span>}
                  </div>

                  {p.gotra_clash_alert && (
                    <div className="badge badge-danger" style={{ whiteSpace: "normal" }}>
                      <AlertTriangle size={13} /> {p.gotra_clash_alert}
                    </div>
                  )}

                  {p.fit_summary && (
                    <p
                      style={{
                        margin: 0,
                        fontSize: "0.84rem",
                        color: "var(--color-ink-2)",
                        display: "-webkit-box",
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: "vertical",
                        overflow: "hidden",
                      }}
                    >
                      {p.fit_summary}
                    </p>
                  )}

                  {nextFu && (
                    <div
                      style={{
                        fontSize: "0.78rem",
                        background: "var(--color-amber-soft)",
                        padding: "0.35rem 0.55rem",
                        borderRadius: "var(--radius-sm)",
                        border: "1px solid var(--color-amber)",
                      }}
                    >
                      <strong>Next Action:</strong> {nextFu.task} ({nextFu.due_date || "Soon"})
                    </div>
                  )}
                </div>

                {/* Footer: 1-Tap WhatsApp + Schedule Call + Archive/Delete (for Saurabh) + Compare */}
                <div
                  style={{
                    borderTop: "1px solid var(--color-rule)",
                    paddingTop: "0.55rem",
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.45rem",
                  }}
                >
                  <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap", alignItems: "center" }}>
                    {p.our_biodata_sent === 1 && <span className="badge">Sister Bio Sent ✓</span>}
                    {p.our_kundli_sent === 1 && <span className="badge">Kundli Sent ✓</span>}
                    {(p.family_votes || []).map((v) => (
                      <span
                        key={v.id}
                        className={`badge ${
                          v.vote === "shortlist"
                            ? "badge-sage"
                            : v.vote === "pass"
                            ? "badge-danger"
                            : "badge-amber"
                        }`}
                      >
                        {v.member_name}:{" "}
                        {v.vote === "shortlist" ? (
                          <ThumbsUp size={11} />
                        ) : v.vote === "pass" ? (
                          <ThumbsDown size={11} />
                        ) : (
                          "?"
                        )}
                      </span>
                    ))}
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.35rem", flexWrap: "wrap" }}>
                    <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className="btn btn-sm btn-primary"
                        onClick={(e) => {
                          e.stopPropagation();
                          setWaModalProfileId(p.id);
                        }}
                        title="1-Tap Send Details or Granular Follow-Up on WhatsApp"
                      >
                        <MessageCircle size={12} /> 1-Tap Message
                      </button>

                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          setMeetingModalState({
                            profileId: p.id,
                            candidateName: p.full_name,
                            meeting: null,
                          });
                        }}
                        title="Schedule Call/Meetup, Alert 2 Phones, or Upload Call Recording"
                      >
                        <Calendar size={12} /> Call / Meet
                      </button>

                      <button
                        type="button"
                        className={`btn btn-sm ${isSelectedForCompare ? "btn-primary" : ""}`}
                        onClick={(e) => toggleCompareId(p.id, e)}
                      >
                        <GitCompare size={12} /> {isSelectedForCompare ? "Selected" : "Compare"}
                      </button>
                    </div>

                    {member.role === "owner" && (
                      <div style={{ display: "flex", gap: "0.25rem" }}>
                        <button
                          type="button"
                          className="btn btn-sm"
                          title={p.status === "Archived" ? "Restore from Archive" : "Archive Profile (Not Needed)"}
                          onClick={(e) => handleArchiveToggle(p, e)}
                        >
                          {p.status === "Archived" ? (
                            <>
                              <ArchiveRestore size={12} /> Restore
                            </>
                          ) : (
                            <>
                              <Archive size={12} /> Archive
                            </>
                          )}
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm"
                          data-state="error"
                          title="Delete Profile Permanently"
                          onClick={(e) => handleDeleteProfile(p, e)}
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 1-Tap WhatsApp Outreach & Granular Follow-Up Modal */}
      {waModalProfileId !== undefined && (
        <WhatsAppComposerModal
          profileId={waModalProfileId}
          onClose={() => setWaModalProfileId(undefined)}
          onSentAndLogged={() => loadData()}
        />
      )}

      {/* 3-Stage Meeting & Call Recording Studio Modal */}
      {meetingModalState && (
        <MeetingStudioModal
          profileId={meetingModalState.profileId}
          candidateName={meetingModalState.candidateName}
          existingMeeting={meetingModalState.meeting}
          onClose={() => setMeetingModalState(null)}
          onSaved={() => loadData()}
        />
      )}
    </div>
  );
};
