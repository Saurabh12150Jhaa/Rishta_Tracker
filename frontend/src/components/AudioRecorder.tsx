import React, { useRef, useState } from "react";
import { Mic, Square, Upload, Volume2 } from "lucide-react";

interface AudioRecorderProps {
  onAudioReady: (file: File) => void;
}

export const AudioRecorder: React.FC<AudioRecorderProps> = ({ onAudioReady }) => {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [recordedName, setRecordedName] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const canUseLiveMic =
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === "function" &&
    (window.isSecureContext || window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1");

  const startRecording = async () => {
    setErrorMsg(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : MediaRecorder.isTypeSupported("audio/mp4")
        ? "audio/mp4"
        : "";
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (ev) => {
        if (ev.data && ev.data.size > 0) chunksRef.current.push(ev.data);
      };

      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const ext = mimeType.includes("mp4") ? "m4a" : "webm";
        const blob = new Blob(chunksRef.current, { type: mimeType || "audio/webm" });
        const fileName = `voice_memo_${new Date().toISOString().slice(11, 19).replace(/:/g, "")}.${ext}`;
        const file = new File([blob], fileName, { type: blob.type });
        setRecordedName(`${fileName} (${Math.max(1, seconds)}s)`);
        onAudioReady(file);
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setSeconds(0);
      setRecording(true);
      timerRef.current = window.setInterval(() => {
        setSeconds((s) => s + 1);
      }, 1000);
    } catch (err: any) {
      setErrorMsg(
        "Live browser mic requires HTTPS or localhost. Use 'Record / Pick Audio File' below (works on HTTP too!)."
      );
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
      onAudioReady(file);
    }
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
        <div className="badge badge-sage" style={{ alignSelf: "flex-start" }}>
          <Volume2 size={13} /> Attached: {recordedName}
        </div>
      )}
      {errorMsg && (
        <div style={{ fontSize: "0.78rem", color: "var(--color-danger)" }}>{errorMsg}</div>
      )}
    </div>
  );
};
