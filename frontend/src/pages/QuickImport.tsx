import React, { useEffect, useState } from "react";
import { CloudOff, FileText, FolderArchive, Image, Layers, Sparkles, UploadCloud, UserPlus } from "lucide-react";
import {
  apiFetch,
  enqueueOfflineCapture,
  listOfflineCaptures,
  OfflineCaptureItem,
  Profile,
  removeOfflineCapture,
} from "../api/client";
import { AudioRecorder } from "../components/AudioRecorder";

interface QuickImportProps {
  preselectedProfileId?: number | null;
  onJobCreated: (jobIds: number[]) => void;
}

export const QuickImport: React.FC<QuickImportProps> = ({ preselectedProfileId, onJobCreated }) => {
  const [mode, setMode] = useState<"auto" | "single" | "batch">(
    preselectedProfileId ? "single" : "auto"
  );
  const [targetProfileId, setTargetProfileId] = useState<string>(
    preselectedProfileId ? String(preselectedProfileId) : ""
  );
  const [existingProfiles, setExistingProfiles] = useState<Profile[]>([]);
  const [savedRelatives, setSavedRelatives] = useState<Array<{ id: number; name: string; relation: string }>>([]);
  const [sourceChannel, setSourceChannel] = useState<string>("Relative");
  const [sourceName, setSourceName] = useState<string>("");
  const [rawText, setRawText] = useState<string>("");
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [offlineOutbox, setOfflineOutbox] = useState<OfflineCaptureItem[]>([]);
  const [syncingOutbox, setSyncingOutbox] = useState<boolean>(false);

  const loadInitial = async () => {
    try {
      const [profRes, relRes] = await Promise.all([
        apiFetch<{ profiles: Profile[] }>("/api/profiles?status=ALL"),
        apiFetch<{ relatives: Array<{ id: number; name: string; relation: string }> }>("/api/relatives"),
      ]);
      setExistingProfiles(profRes.profiles || []);
      setSavedRelatives(relRes.relatives || []);
    } catch {
      // Offline mode allowed
    }
    const queued = await listOfflineCaptures();
    setOfflineOutbox(queued);
  };

  useEffect(() => {
    loadInitial();
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []);
    if (selected.length > 0) {
      setFiles((prev) => [...prev, ...selected]);
      const pdfCount = [...files, ...selected].filter((f) => f.name.toLowerCase().endsWith(".pdf")).length;
      if (pdfCount > 1 && !targetProfileId) {
        setMode("batch");
      }
    }
  };

  const handleAudioRecorded = (file: File | null) => {
    if (file) setFiles((prev) => [...prev, file]);
  };

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);

    if (!rawText.trim() && files.length === 0) {
      setErrorMsg("Paste a WhatsApp message/call note or attach at least one PDF, photo, voice note, or .zip file.");
      return;
    }

    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("mode", mode);
      if (targetProfileId) fd.append("target_profile_id", targetProfileId);
      fd.append("raw_text", rawText);
      fd.append("source_channel", sourceChannel);
      if (sourceName.trim()) fd.append("source_name", sourceName.trim());
      files.forEach((f) => fd.append("files", f));

      const res = await apiFetch<{ mode: string; jobs: Array<{ job_id: number }> }>(
        "/api/imports/process",
        {
          method: "POST",
          body: fd,
        }
      );
      const jobIds = (res.jobs || []).map((j) => j.job_id);
      onJobCreated(jobIds);
    } catch (err: any) {
      // If Mac server is unreachable (e.g. outside home Wi-Fi or Mac lid closed), offer offline outbox save
      if (rawText.trim() && (err.message.includes("Failed to fetch") || err.message.includes("NetworkError"))) {
        await enqueueOfflineCapture({
          raw_text: rawText,
          source_name: sourceName,
          source_channel: sourceChannel,
          created_at: new Date().toISOString(),
        });
        setRawText("");
        setOfflineOutbox(await listOfflineCaptures());
        setErrorMsg(
          "Mac server is currently unreachable — saved your note in the Android Offline Outbox! Tap 'Sync Outbox' once back on home Wi-Fi."
        );
      } else {
        setErrorMsg(err.message || "Failed to process import");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const syncOfflineOutbox = async () => {
    setSyncingOutbox(true);
    const createdIds: number[] = [];
    try {
      for (const item of offlineOutbox) {
        const fd = new FormData();
        fd.append("mode", "single");
        fd.append("raw_text", item.raw_text);
        fd.append("source_name", item.source_name || "");
        fd.append("source_channel", item.source_channel || "Relative");
        const res = await apiFetch<{ jobs: Array<{ job_id: number }> }>("/api/imports/process", {
          method: "POST",
          body: fd,
        });
        if (item.id) await removeOfflineCapture(item.id);
        createdIds.push(...(res.jobs || []).map((j) => j.job_id));
      }
      setOfflineOutbox(await listOfflineCaptures());
      if (createdIds.length > 0) onJobCreated(createdIds);
    } catch (err: any) {
      setErrorMsg(`Could not sync outbox yet: ${err.message}`);
    } finally {
      setSyncingOutbox(false);
    }
  };

  return (
    <div style={{ maxWidth: 820, margin: "0 auto", display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
      {offlineOutbox.length > 0 && (
        <div className="card" style={{ background: "var(--color-amber-soft)", borderColor: "var(--color-amber)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
            <div>
              <strong>
                <CloudOff size={15} style={{ verticalAlign: "middle" }} /> {offlineOutbox.length} Offline Capture(s) Queued on Device
              </strong>
              <div style={{ fontSize: "0.82rem" }}>Ready to send to Mac AI server over Wi-Fi</div>
            </div>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              data-state={syncingOutbox ? "loading" : undefined}
              onClick={syncOfflineOutbox}
            >
              {syncingOutbox ? "Syncing..." : "Sync Outbox Now"}
            </button>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="card" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <div>
          <div className="mono-label">Multimodal Rishta Capture Studio</div>
          <h1 style={{ fontSize: "1.45rem" }}>Import from WhatsApp, Biodata PDF, Voice Note, or .ZIP</h1>
          <p style={{ margin: "0.25rem 0 0", fontSize: "0.86rem", color: "var(--color-ink-2)" }}>
            Powered on your Mac by <strong>gpt-5.4</strong> (Vision OCR), <strong>gemini-3-flash</strong> (Hinglish Voice),{" "}
            <strong>claude-sonnet-4-6</strong> (Advisor), &amp; <strong>text-embedding-3-large</strong> (Deduplication).
          </p>
        </div>

        {/* Smart AI Auto-Segregation vs Single vs Batch Mode */}
        <div className="card-subtle" style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          <div className="mono-label">AI Segregation &amp; Existing-Profile Auto-Linker</div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button
              type="button"
              className={`btn btn-sm ${mode === "auto" ? "btn-primary" : ""}`}
              onClick={() => {
                setMode("auto");
                setTargetProfileId("");
              }}
            >
              <Sparkles size={14} /> Smart AI Auto-Segregate &amp; Link to Existing Profiles (Recommended)
            </button>
            <button
              type="button"
              className={`btn btn-sm ${mode === "single" ? "btn-primary" : ""}`}
              onClick={() => setMode("single")}
            >
              <UserPlus size={14} /> Single Prospect (Combine all files into 1 person)
            </button>
            <button
              type="button"
              className={`btn btn-sm ${mode === "batch" ? "btn-primary" : ""}`}
              onClick={() => {
                setMode("batch");
                setTargetProfileId("");
              }}
            >
              <Layers size={14} /> Batch Mode (Force split multiple PDFs / .ZIP)
            </button>
          </div>
          <div style={{ fontSize: "0.78rem", color: "var(--color-ink-2)" }}>
            In <strong>Smart AI Auto-Segregate</strong> mode, <code>gpt-5.4</code> / <code>claude-opus-4-6</code>{" "}
            automatically identifies if your text, PDF, voice note, or <code>.zip</code> contains 1 or multiple people,
            links updates to any matching existing profile, and stages each section for your review!
          </div>
        </div>

        <div className="grid-2col">
          <div>
            <label className="mono-label" style={{ display: "block", marginBottom: "0.3rem" }}>
              Target Profile (Leave on Auto-Detect or Lock to a Specific Profile)
            </label>
            <select
              className="select"
              value={targetProfileId}
              onChange={(e) => {
                setTargetProfileId(e.target.value);
                if (e.target.value) setMode("single");
              }}
            >
              <option value="">✨ Let AI Auto-Identify Existing Profile or Create New</option>
              {existingProfiles.map((p) => (
                <option key={p.id} value={String(p.id)}>
                  Lock to #{p.id}: {p.full_name} ({p.current_city || p.status})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="mono-label" style={{ display: "block", marginBottom: "0.3rem" }}>
              Source Channel
            </label>
            <select
              className="select"
              value={sourceChannel}
              onChange={(e) => setSourceChannel(e.target.value)}
            >
              <option value="Relative">Family / Relative (Mausi, Bua, Uncle)</option>
              <option value="Marriage Bureau">Marriage Bureau / Panditji / Broker</option>
              <option value="Matrimonial App">Matrimonial App (Jeevansathi / Shaadi)</option>
              <option value="Direct / Friend">Direct / Family Friend</option>
            </select>
          </div>

          <div>
            <label className="mono-label" style={{ display: "block", marginBottom: "0.3rem" }}>
              Referred By (Pick Saved Relative or Type New)
            </label>
            <div style={{ display: "flex", gap: "0.4rem" }}>
              {savedRelatives.length > 0 && (
                <select
                  className="select"
                  style={{ maxWidth: 185 }}
                  value=""
                  onChange={(e) => {
                    if (e.target.value) setSourceName(e.target.value);
                  }}
                >
                  <option value="">Pick saved...</option>
                  {savedRelatives.map((r) => (
                    <option key={r.id} value={r.name}>
                      {r.name} ({r.relation})
                    </option>
                  ))}
                </select>
              )}
              <input
                type="text"
                className="input"
                placeholder="e.g. Sunita Mausi, Khanna Bureau (auto-saves)"
                value={sourceName}
                onChange={(e) => setSourceName(e.target.value)}
              />
            </div>
          </div>
        </div>

        {/* Pasted WhatsApp Message or Call Recap */}
        <div>
          <label className="mono-label" style={{ display: "block", marginBottom: "0.3rem" }}>
            Paste WhatsApp Forward, Bio Text, or Phone Call Notes (English / Hinglish)
          </label>
          <textarea
            className="textarea"
            rows={5}
            placeholder="Paste forwarded WhatsApp message, parent call notes, or kundli details here..."
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
          />
          {/(jeevansathi|shaadi)\.com|bharatmatrimony\.com/i.test(rawText) && files.length === 0 && (
            <div style={{ fontSize: "0.8rem", color: "var(--color-ink-2)", marginTop: "0.35rem" }}>
              Jeevansathi doesn&apos;t allow apps to read profiles automatically. Share screenshots of the profile pages
              (or copy-paste the profile text) — they&apos;ll be matched to this profile by its ID.
            </div>
          )}
        </div>

        {/* Live Voice Recorder or .opus Picker */}
        <AudioRecorder onAudioReady={handleAudioRecorded} />

        {/* Multimodal File Upload Dropzone */}
        <div
          className="card-subtle"
          style={{
            borderStyle: "dashed",
            borderWidth: "1.5px",
            borderColor: "var(--color-rule-strong)",
            textAlign: "center",
            padding: "1.1rem",
          }}
        >
          <UploadCloud size={26} color="var(--color-accent)" style={{ marginBottom: "0.3rem" }} />
          <div style={{ fontWeight: 600, fontSize: "0.92rem" }}>
            Attach Handwritten Diary Photos, Biodata PDFs, Screenshots, Voice Notes (.opus), Excel/CSV/Word, vCards (.vcf), or Chat (.zip)
          </div>
          <div style={{ fontSize: "0.78rem", color: "var(--color-ink-muted)", marginBottom: "0.65rem" }}>
            Handwritten Hindi/English multi-row registers &amp; portrait photos inside PDFs are extracted automatically!
          </div>
          <label className="btn btn-sm" style={{ cursor: "pointer" }}>
            Choose Files from Phone / Mac
            <input
              type="file"
              multiple
              accept=".pdf,image/*,audio/*,.opus,.ogg,.m4a,.mp3,.wav,.aac,.webm,.zip,.vcf,.csv,.tsv,.docx,.xlsx"
              style={{ display: "none" }}
              onChange={handleFileSelect}
            />
          </label>

          {files.length > 0 && (
            <div style={{ marginTop: "0.8rem", display: "flex", gap: "0.4rem", flexWrap: "wrap", justifyContent: "center" }}>
              {files.map((f, idx) => (
                <span key={idx} className="badge badge-accent" style={{ gap: "0.4rem" }}>
                  {f.name.endsWith(".pdf") ? (
                    <FileText size={12} />
                  ) : f.name.endsWith(".zip") ? (
                    <FolderArchive size={12} />
                  ) : (
                    <Image size={12} />
                  )}
                  {f.name}
                  <button
                    type="button"
                    onClick={() => removeFile(idx)}
                    style={{
                      border: "none",
                      background: "transparent",
                      color: "inherit",
                      cursor: "pointer",
                      fontWeight: 700,
                      padding: 0,
                    }}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {errorMsg && (
          <div className="card" style={{ background: "var(--color-danger-soft)", borderColor: "var(--color-danger)", color: "var(--color-danger)" }}>
            {errorMsg}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.6rem" }}>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={submitting}
            data-state={submitting ? "loading" : undefined}
          >
            <Sparkles size={16} />
            {submitting
              ? "Running Mac Multi-Model AI Extraction..."
              : mode === "batch"
              ? "Process Batch with Mac AI"
              : "Extract & Review with Mac AI"}
          </button>
        </div>
      </form>
    </div>
  );
};
