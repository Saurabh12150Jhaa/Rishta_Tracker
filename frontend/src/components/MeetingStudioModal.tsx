import React, { useEffect, useState } from "react";
import {
  BellRing,
  Calendar,
  CheckCircle2,
  Download,
  ExternalLink,
  FileAudio,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { apiFetch, MeetingItem } from "../api/client";
import { AudioRecorder } from "./AudioRecorder";

interface MeetingStudioModalProps {
  profileId: number;
  candidateName: string;
  existingMeeting?: MeetingItem | null;
  defaultPreCallNotes?: string;
  onClose: () => void;
  onSaved: () => void;
}

export const MeetingStudioModal: React.FC<MeetingStudioModalProps> = ({
  profileId,
  candidateName,
  existingMeeting,
  defaultPreCallNotes = "",
  onClose,
  onSaved,
}) => {
  const [stage, setStage] = useState<"proposing" | "scheduled" | "completed">(
    (existingMeeting?.stage as any) || "scheduled"
  );
  const [quickParseInput, setQuickParseInput] = useState<string>("");
  const [parsingAi, setParsingAi] = useState<boolean>(false);

  const [meetingType, setMeetingType] = useState<string>(
    existingMeeting?.meeting_type || "Family Phone Call"
  );
  const [title, setTitle] = useState<string>(
    existingMeeting?.title || `Phone Call — ${candidateName}`
  );
  const [proposedSlotsText, setProposedSlotsText] = useState<string>(
    existingMeeting?.proposed_slots_text || "This Saturday 7:30 PM or Sunday 11:30 AM"
  );
  const [scheduledAt, setScheduledAt] = useState<string>(
    existingMeeting?.scheduled_at || ""
  );
  const [locationOrLink, setLocationOrLink] = useState<string>(
    existingMeeting?.location_or_link || "Phone / WhatsApp Call"
  );
  const [participants, setParticipants] = useState<string>(
    existingMeeting?.participants || "Saurabh, Mummy & Prospect's Family"
  );
  const [preMeetingNotes, setPreMeetingNotes] = useState<string>(
    existingMeeting?.pre_meeting_notes || defaultPreCallNotes
  );
  const [reminderMinutes, setReminderMinutes] = useState<number>(
    existingMeeting?.reminder_minutes || 30
  );
  const [notifyPhone1, setNotifyPhone1] = useState<boolean>(
    existingMeeting ? existingMeeting.notify_phone_1 === 1 : true
  );
  const [notifyPhone2, setNotifyPhone2] = useState<boolean>(
    existingMeeting ? existingMeeting.notify_phone_2 === 1 : true
  );

  // Stage 3: Post-Meeting Call Recording & Notes
  const [postMeetingNotes, setPostMeetingNotes] = useState<string>(
    existingMeeting?.post_meeting_notes || ""
  );
  const [recordingFile, setRecordingFile] = useState<File | null>(null);
  const [saving, setSaving] = useState<boolean>(false);
  const [savedMeeting, setSavedMeeting] = useState<MeetingItem | null>(existingMeeting || null);
  const [alertFeedback, setAlertFeedback] = useState<any>(null);

  useEffect(() => {
    if (!scheduledAt) {
      const tomorrow = new Date(Date.now() + 86400000);
      tomorrow.setHours(19, 30, 0, 0);
      const isoLocal = new Date(tomorrow.getTime() - tomorrow.getTimezoneOffset() * 60000)
        .toISOString()
        .slice(0, 16);
      setScheduledAt(isoLocal);
    }
  }, []);

  const handleQuickAiParse = async () => {
    if (!quickParseInput.trim()) return;
    setParsingAi(true);
    try {
      const res = await apiFetch<any>("/api/meetings/quick-parse", {
        method: "POST",
        body: JSON.stringify({ text: quickParseInput }),
      });
      if (res.stage === "proposing" || res.stage === "scheduled") setStage(res.stage);
      if (res.meeting_type) setMeetingType(res.meeting_type);
      if (res.title) setTitle(res.title);
      if (res.proposed_slots_text) setProposedSlotsText(res.proposed_slots_text);
      if (res.scheduled_at) setScheduledAt(res.scheduled_at.slice(0, 16));
      if (res.location_or_link) setLocationOrLink(res.location_or_link);
      if (res.participants) setParticipants(res.participants);
      if (res.pre_meeting_notes) setPreMeetingNotes(res.pre_meeting_notes);
    } catch (err: any) {
      alert(err.message);
    } finally {
      setParsingAi(false);
    }
  };

  const handleSaveBeforeOrScheduled = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        stage,
        meeting_type: meetingType,
        title,
        proposed_slots_text: proposedSlotsText,
        scheduled_at: stage === "scheduled" ? scheduledAt : null,
        location_or_link: locationOrLink,
        participants,
        pre_meeting_notes: preMeetingNotes,
        reminder_minutes: reminderMinutes,
        notify_phone_1: notifyPhone1,
        notify_phone_2: notifyPhone2,
        send_immediate_alert: stage === "scheduled",
      };

      let res: MeetingItem;
      if (savedMeeting?.id) {
        res = await apiFetch<MeetingItem>(`/api/meetings/${savedMeeting.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        res = await apiFetch<MeetingItem>(`/api/profiles/${profileId}/meetings`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      setSavedMeeting(res);
      if ((res as any).alert_dispatch) {
        setAlertFeedback((res as any).alert_dispatch);
      }
      onSaved();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleCompleteWithRecording = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      let meetingId = savedMeeting?.id;
      if (!meetingId) {
        const created = await apiFetch<MeetingItem>(`/api/profiles/${profileId}/meetings`, {
          method: "POST",
          body: JSON.stringify({
            stage: "scheduled",
            meeting_type: meetingType,
            title,
            scheduled_at: scheduledAt,
            participants,
            pre_meeting_notes: preMeetingNotes,
            send_immediate_alert: false,
          }),
        });
        meetingId = created.id;
      }

      const fd = new FormData();
      fd.append("post_meeting_notes", postMeetingNotes);
      if (recordingFile) {
        fd.append("recording_file", recordingFile);
      }

      const res = await apiFetch<any>(`/api/meetings/${meetingId}/complete-with-recording`, {
        method: "POST",
        body: fd,
      });
      setSavedMeeting(res.meeting);
      onSaved();
      onClose();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setSaving(false);
    }
  };

  const triggerManualTwoPhoneAlert = async () => {
    if (!savedMeeting?.id) return;
    const res = await apiFetch<any>(`/api/meetings/${savedMeeting.id}/send-reminder`, {
      method: "POST",
    });
    setAlertFeedback(res);
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 80,
        background: "rgba(25, 20, 15, 0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1rem",
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{
          width: "100%",
          maxWidth: 760,
          maxHeight: "92dvh",
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: "0.85rem",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.5rem" }}>
          <div>
            <div className="mono-label">
              <Calendar size={12} style={{ verticalAlign: "middle" }} /> 3-Stage Meeting &amp; Call Recording Studio
            </div>
            <h2 style={{ fontSize: "1.3rem" }}>
              Schedule, Alert 2 Phones, &amp; Upload Call Recording — {candidateName}
            </h2>
          </div>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            <X size={15} /> Close
          </button>
        </div>

        {/* Effortless AI Natural-Language Quick Fill */}
        <div className="card-subtle" style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
          <input
            type="text"
            className="input"
            style={{ flex: "1 1 280px" }}
            placeholder="Quick AI Fill: e.g. 'Call with father tomorrow at 7:30 PM to discuss kundli & Bangalore'"
            value={quickParseInput}
            onChange={(e) => setQuickParseInput(e.target.value)}
          />
          <button
            type="button"
            className="btn btn-sm btn-primary"
            data-state={parsingAi ? "loading" : undefined}
            onClick={handleQuickAiParse}
          >
            <Sparkles size={13} /> {parsingAi ? "Parsing..." : "AI Auto-Fill"}
          </button>
        </div>

        {/* 3-Stage Selector Tabs */}
        <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
          <button
            type="button"
            className={`btn btn-sm ${stage === "proposing" ? "btn-primary" : ""}`}
            onClick={() => setStage("proposing")}
          >
            1. Before Scheduling (Propose Slots &amp; Prep)
          </button>
          <button
            type="button"
            className={`btn btn-sm ${stage === "scheduled" ? "btn-primary" : ""}`}
            onClick={() => setStage("scheduled")}
          >
            2. Confirmed Schedule &amp; 2-Phone Reminder
          </button>
          <button
            type="button"
            className={`btn btn-sm ${stage === "completed" ? "btn-primary" : ""}`}
            onClick={() => setStage("completed")}
          >
            3. Done — Upload Call Recording / Debrief
          </button>
        </div>

        {stage !== "completed" ? (
          <form onSubmit={handleSaveBeforeOrScheduled} style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <div className="grid-2col">
              <div>
                <label className="mono-label">Meeting / Call Type</label>
                <select className="select" value={meetingType} onChange={(e) => setMeetingType(e.target.value)}>
                  <option value="Family Phone Call">Family Intro Phone Call</option>
                  <option value="1:1 Prospect Call">Sister &amp; Prospect 1:1 Call</option>
                  <option value="Video Call">Family / 1:1 Video Call</option>
                  <option value="In-Person Meetup">In-Person Meetup</option>
                </select>
              </div>

              <div>
                <label className="mono-label">Meeting Title</label>
                <input
                  type="text"
                  className="input"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                />
              </div>

              {stage === "proposing" ? (
                <div style={{ gridColumn: "1 / -1" }}>
                  <label className="mono-label">Proposed Time Slots (Before Scheduling)</label>
                  <input
                    type="text"
                    className="input"
                    placeholder="e.g. Saturday 7:30 PM or Sunday 11:30 AM"
                    value={proposedSlotsText}
                    onChange={(e) => setProposedSlotsText(e.target.value)}
                  />
                </div>
              ) : (
                <>
                  <div>
                    <label className="mono-label">Confirmed Date &amp; Time</label>
                    <input
                      type="datetime-local"
                      className="input"
                      value={scheduledAt}
                      onChange={(e) => setScheduledAt(e.target.value)}
                      required
                    />
                  </div>
                  <div>
                    <label className="mono-label">Send Reminder Before Meeting</label>
                    <select
                      className="select"
                      value={String(reminderMinutes)}
                      onChange={(e) => setReminderMinutes(Number(e.target.value))}
                    >
                      <option value="15">15 minutes before</option>
                      <option value="30">30 minutes before</option>
                      <option value="60">1 hour before</option>
                      <option value="180">3 hours before</option>
                    </select>
                  </div>
                </>
              )}

              <div>
                <label className="mono-label">Participants</label>
                <input
                  type="text"
                  className="input"
                  value={participants}
                  onChange={(e) => setParticipants(e.target.value)}
                />
              </div>

              <div>
                <label className="mono-label">Phone / Video Link / Venue</label>
                <input
                  type="text"
                  className="input"
                  value={locationOrLink}
                  onChange={(e) => setLocationOrLink(e.target.value)}
                />
              </div>
            </div>

            <div>
              <label className="mono-label">Pre-Meeting Talking Points &amp; Questions to Cover</label>
              <textarea
                className="textarea"
                rows={3}
                placeholder="Questions we want to clarify on this call (included in your phone reminder!)..."
                value={preMeetingNotes}
                onChange={(e) => setPreMeetingNotes(e.target.value)}
              />
            </div>

            {stage === "scheduled" && (
              <div className="card-subtle" style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
                <span className="mono-label">
                  <BellRing size={12} style={{ verticalAlign: "middle" }} /> Devices to Alert:
                </span>
                <label style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", fontSize: "0.85rem", fontWeight: 600 }}>
                  <input
                    type="checkbox"
                    checked={notifyPhone1}
                    onChange={(e) => setNotifyPhone1(e.target.checked)}
                  />
                  Phone 1 (Saurabh&apos;s Phone)
                </label>
                <label style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", fontSize: "0.85rem", fontWeight: 600 }}>
                  <input
                    type="checkbox"
                    checked={notifyPhone2}
                    onChange={(e) => setNotifyPhone2(e.target.checked)}
                  />
                  Phone 2 (Mummy / Sister&apos;s Phone)
                </label>
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", flexWrap: "wrap" }}>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={saving}
                data-state={saving ? "loading" : undefined}
              >
                <CheckCircle2 size={15} />{" "}
                {saving
                  ? "Saving..."
                  : stage === "proposing"
                  ? "Save Slot Proposal & Prep"
                  : "Confirm Schedule & Arm 2-Phone Reminders"}
              </button>
            </div>

            {/* Post-Save Quick Actions: WhatsApp Slot Proposal / Google Calendar / 2-Phone Alert */}
            {savedMeeting && (
              <div
                className="card-subtle"
                style={{
                  background: "var(--color-sage-soft)",
                  borderColor: "var(--color-sage)",
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.55rem",
                }}
              >
                <strong>Saved! One-Tap Actions for Phones &amp; Calendar:</strong>
                <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                  {savedMeeting.whatsapp_slot_proposal_text && (
                    <a
                      href={`https://wa.me/?text=${encodeURIComponent(savedMeeting.whatsapp_slot_proposal_text)}`}
                      target="_blank"
                      rel="noreferrer"
                      className="btn btn-sm btn-primary"
                    >
                      <ExternalLink size={13} /> Send Slot Proposal on WhatsApp
                    </a>
                  )}
                  {savedMeeting.google_calendar_url && (
                    <a
                      href={savedMeeting.google_calendar_url}
                      target="_blank"
                      rel="noreferrer"
                      className="btn btn-sm"
                    >
                      <Calendar size={13} /> Add to Google Calendar (Rings Both Phones)
                    </a>
                  )}
                  {savedMeeting.ics_download_url && (
                    <a href={savedMeeting.ics_download_url} className="btn btn-sm">
                      <Download size={13} /> Download .ICS Phone Alarm
                    </a>
                  )}
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={triggerManualTwoPhoneAlert}
                  >
                    <BellRing size={13} /> Send Alert to Phone 1 &amp; Phone 2 Now
                  </button>
                </div>

                {alertFeedback && (
                  <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.25rem" }}>
                    <span className="badge badge-sage">
                      Triggered: {(alertFeedback.sent_channels || []).join(" + ")}
                    </span>
                    {alertFeedback.phone_1_wa_url && (
                      <a
                        href={alertFeedback.phone_1_wa_url}
                        target="_blank"
                        rel="noreferrer"
                        className="btn btn-sm"
                      >
                        WhatsApp Alert → Phone 1
                      </a>
                    )}
                    {alertFeedback.phone_2_wa_url && (
                      <a
                        href={alertFeedback.phone_2_wa_url}
                        target="_blank"
                        rel="noreferrer"
                        className="btn btn-sm"
                      >
                        WhatsApp Alert → Phone 2
                      </a>
                    )}
                  </div>
                )}
              </div>
            )}
          </form>
        ) : (
          /* Stage 3: Post-Meeting Call Recording Upload & AI Analysis */
          <form onSubmit={handleCompleteWithRecording} style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
            <div className="card-subtle">
              <div style={{ fontWeight: 700, marginBottom: "0.25rem" }}>
                <FileAudio size={15} style={{ verticalAlign: "middle" }} /> Upload Call Recording or Record Post-Call Debrief
              </div>
              <p style={{ margin: "0 0 0.6rem", fontSize: "0.83rem", color: "var(--color-ink-2)" }}>
                Share the phone call recording (<code>.m4a</code>, <code>.mp3</code>, <code>.amr</code>, <code>.wav</code>,{" "}
                <code>.opus</code>, <code>.ogg</code>) from your Android phone. Mac AI (<strong>gemini-3-flash</strong> +{" "}
                <strong>gpt-5.4</strong> + <strong>claude-sonnet-4-6</strong>) will transcribe the full Hinglish/English
                conversation, extract new facts into the dossier, and create the next follow-up!
              </p>

              <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", alignItems: "center" }}>
                <label className="btn btn-sm btn-primary" style={{ cursor: "pointer" }}>
                  <Upload size={14} /> Choose Call Recording File
                  <input
                    type="file"
                    accept="audio/*,.m4a,.mp3,.amr,.wav,.opus,.ogg,.aac,.webm"
                    style={{ display: "none" }}
                    onChange={(e) => setRecordingFile(e.target.files?.[0] || null)}
                  />
                </label>
                {recordingFile && (
                  <span className="badge badge-sage">Selected: {recordingFile.name}</span>
                )}
              </div>
            </div>

            <AudioRecorder onAudioReady={(file) => setRecordingFile(file)} />

            <div>
              <label className="mono-label">Post-Call / Post-Meetup Notes (Optional)</label>
              <textarea
                className="textarea"
                rows={4}
                placeholder="Any additional impressions, family feedback, or next steps agreed on the call..."
                value={postMeetingNotes}
                onChange={(e) => setPostMeetingNotes(e.target.value)}
              />
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={saving}
                data-state={saving ? "loading" : undefined}
              >
                <Sparkles size={15} />{" "}
                {saving
                  ? "Transcribing Call Recording & Updating Profile..."
                  : "Complete Meeting & Analyze Call Recording with AI"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
