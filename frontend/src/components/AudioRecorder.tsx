import React, { useEffect, useRef, useState } from "react";
import { Mic, Square, Trash2, Upload, Volume2 } from "lucide-react";

interface AudioRecorderProps {
  onAudioReady: (file: File | null) => void;
}

const PREFERRED_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

export const AudioRecorder: React.FC<AudioRecorderProps> = ({ onAudioReady }) => {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [recordedName, setRecordedName] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<number | null>(null);
  const secondsRef = useRef(0);
  const previewUrlRef = useRef<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const isSecure =
    typeof window !== "undefined" &&
    (window.isSecureContext || window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1");
  const canUseLiveMic =
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === "function" &&
    isSecure;

  const replacePreview = (blob: Blob | null) => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    const url = blob ? URL.createObjectURL(blob) : null;
    previewUrlRef.current = url;
    setPreviewUrl(url);
  };

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
      const rec = mediaRecorderRef.current;
      if (rec && rec.state !== "inactive") {
        rec.stream.getTracks().forEach((t) => t.stop());
      }
    };
  }, []);

  const startRecording = async () => {
    setErrorMsg(null);
    if (!isSecure) {
      setErrorMsg(
        "Live browser mic requires HTTPS or localhost. Use 'Record / Pick Audio File' below (works on HTTP too!)."
      );
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = PREFERRED_MIME_TYPES.find((t) => MediaRecorder.isTypeSupported(t)) || "";
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (ev) => {
        if (ev.data && ev.data.size > 0) chunksRef.current.push(ev.data);
      };

      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const baseType = (mimeType || "audio/webm").split(";")[0];
        const ext = baseType.includes("mp4") ? "m4a" : "webm";
        const blob = new Blob(chunksRef.current, { type: baseType });
        const fileName = `voice_memo_${new Date().toISOString().slice(11, 19).replace(/:/g, "")}.${ext}`;
        const file = new File([blob], fileName, { type: blob.type });
        setRecordedName(`${fileName} (${Math.max(1, secondsRef.current)}s)`);
        replacePreview(blob);
        onAudioReady(file);
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      secondsRef.current = 0;
      setSeconds(0);
      setRecording(true);
      timerRef.current = window.setInterval(() => {
        secondsRef.current += 1;
        setSeconds(secondsRef.current);
      }, 1000);
    } catch (err: any) {
      if (err?.name === "NotAllowedError" || err?.name === "SecurityError") {
        setErrorMsg("Microphone permission denied — allow mic for this site in browser settings");
      } else if (err?.name === "NotFoundError" || err?.name === "OverconstrainedError") {
        setErrorMsg("No microphone found");
      } else {
        setErrorMsg(err?.message || "Could not start recording");
      }
    }
  };

  const stopRecording = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    setRecording(false);
  };

  const handleNativeAudioPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setRecordedName(file.name);
      replacePreview(file);
      onAudioReady(file);
    }
    e.target.value = "";
  };

  const handleDiscard = () => {
    setRecordedName(null);
    replacePreview(null);
    onAudioReady(null);
  };

  return (
    <div className="card-subtle" style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem" }}>
        <div>
          <div className="mono-label">Hinglish Voice Note / Call Recap</div>
          <div style={{ fontSize: "0.82rem", color: "var(--color-ink-2)" }}>
            Speak in Hindi + English (e.g. &ldquo;Papa talked to father, kundli needed, package 35 LPA&rdquo;)
          </div>
        </div>
        <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
          {canUseLiveMic && !recording && (
            <button type="button" className="btn btn-primary btn-sm" onClick={startRecording}>
              <Mic size={14} /> Record Voice Memo
            </button>
          )}
          {recording && (
            <button type="button" className="btn btn-sm" data-state="error" onClick={stopRecording}>
              <Square size={14} /> Stop ({seconds}s)
            </button>
          )}
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => fileInputRef.current?.click()}
          >
            <Upload size={14} /> {canUseLiveMic ? "Pick .opus / Audio" : "Record / Pick Audio"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="audio/*,.opus,.ogg,.m4a,.mp3,.wav,.aac,.webm"
            capture="user"
            style={{ display: "none" }}
            onChange={handleNativeAudioPick}
          />
        </div>
      </div>

      {recordedName && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
          <div className="badge badge-sage">
            <Volume2 size={13} /> Attached: {recordedName}
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={handleDiscard}>
            <Trash2 size={13} /> Discard
          </button>
        </div>
      )}
      {previewUrl && <audio controls src={previewUrl} style={{ width: "100%", maxWidth: 420 }} />}
      {errorMsg && (
        <div style={{ fontSize: "0.78rem", color: "var(--color-danger)" }}>{errorMsg}</div>
      )}
    </div>
  );
};
