import React, { useEffect, useState } from "react";
import { Check, Copy, ExternalLink, MessageCircle, Send, Sparkles, X } from "lucide-react";
import { apiFetch, RelativeItem } from "../api/client";

interface WhatsAppComposerModalProps {
  profileId?: number | null;
  initialPhone?: string;
  initialRecipientLabel?: string;
  onClose: () => void;
  onSentAndLogged?: () => void;
}

interface TemplateOption {
  id: string;
  category: "first_time" | "follow_up";
  stage_label: string;
  audience: string;
  text: string;
}

export const WhatsAppComposerModal: React.FC<WhatsAppComposerModalProps> = ({
  profileId,
  initialPhone = "",
  initialRecipientLabel = "",
  onClose,
  onSentAndLogged,
}) => {
  const [categoryTab, setCategoryTab] = useState<"first_time" | "follow_up">("first_time");
  const [templates, setTemplates] = useState<TemplateOption[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");
  const [messageText, setMessageText] = useState<string>("");
  const [recipients, setRecipients] = useState<Array<{ label: string; phone: string; type: string }>>([]);
  const [targetPhone, setTargetPhone] = useState<string>(initialPhone);
  const [logToTimeline, setLogToTimeline] = useState<boolean>(true);
  const [copied, setCopied] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [candidateName, setCandidateName] = useState<string>("");

  useEffect(() => {
    setLoading(true);
    if (profileId) {
      apiFetch<any>(`/api/profiles/${profileId}/whatsapp-templates`)
        .then((res) => {
          setCandidateName(res.full_name || "Candidate");
          const tList: TemplateOption[] = res.templates || [];
          setTemplates(tList);
          const recs = res.recipients || [];
          setRecipients(recs);
          if (!initialPhone && recs.length > 0) {
            setTargetPhone(recs[0].phone);
          }
          const firstMatch = tList.find((t) => t.category === "first_time") || tList[0];
          if (firstMatch) {
            setSelectedTemplateId(firstMatch.id);
            setMessageText(firstMatch.text);
          }
        })
        .finally(() => setLoading(false));
    } else {
      // Standalone mode (sending Sister's Outbound Pack or general follow-up to any Relative / new contact)
      Promise.all([
        apiFetch<any>("/api/settings"),
        apiFetch<{ relatives: RelativeItem[] }>("/api/relatives"),
      ])
        .then(([setRes, relRes]) => {
          const outbound = setRes.settings?.my_outbound_pack || {};
          const sisterBio =
            outbound.shareable_whatsapp_bio ||
            "Namaste! Sharing my sister's profile details for your review.";
          const generalTemplates: TemplateOption[] = [
            {
              id: "standalone_first_sister_bio",
              category: "first_time",
              stage_label: "1st Time · Send Sister's Biodata & Details to Any Family / Relative",
              audience: "Anyone (New Contact or Relative)",
              text: `${sisterBio}\n\nWarm regards,\nSaurabh & Family`,
            },
            {
              id: "standalone_first_ask_relative",
              category: "first_time",
              stage_label: "1st Time · Ask Relative / Mediator to Look for Matches for Sister",
              audience: "Relative / Mediator",
              text: (
                `Namaste ${initialRecipientLabel || "ji"}! 🙏\n` +
                `Hope everyone at home is doing well. Sharing my sister's updated profile details below—please do keep her in mind and share if you come across any suitable, well-educated groom/family:\n\n` +
                `${sisterBio}\n\nWarm regards,\nSaurabh & Mummy`
              ),
            },
            {
              id: "standalone_followup_relative_check",
              category: "follow_up",
              stage_label: "Follow-Up #1 · Check In with Relative / Mediator on Shared Profiles",
              audience: "Relative / Mediator",
              text: (
                `Namaste ${initialRecipientLabel || "ji"}! 🙏\n` +
                `Hope you are doing well. Just checking in to see if there was any update from the families we discussed earlier regarding my sister's profile, or if any new suitable profiles have come up.\n\nWarm regards,\nSaurabh`
              ),
            },
            {
              id: "standalone_followup_kundli_share",
              category: "follow_up",
              stage_label: "Follow-Up #2 · Share Sister's Kundli / Birth Details Only",
              audience: "Prospect Family / Panditji / Relative",
              text: (
                `Namaste! 🙏 Sharing my sister's birth details for Kundli matching:\n` +
                `• Name: ${outbound.my_full_name || "Sister"}\n` +
                `• Date of Birth: ${outbound.my_dob || "—"}\n` +
                `• Time of Birth: ${outbound.my_tob || "—"}\n` +
                `• Place of Birth: ${outbound.my_pob || "—"}\n` +
                `• Gotra: ${outbound.my_gotra || "—"}\n\n` +
                `Please let us know once you have had a chance to check.`
              ),
            },
          ];
          setTemplates(generalTemplates);
          setSelectedTemplateId(generalTemplates[0].id);
          setMessageText(generalTemplates[0].text);
          const recs = (relRes.relatives || [])
            .filter((r) => r.phone)
            .map((r) => ({
              label: `${r.name} (${r.relation} · ${r.phone})`,
              phone: r.phone || "",
              type: "relative",
            }));
          setRecipients(recs);
          if (!initialPhone && recs.length > 0) {
            setTargetPhone(recs[0].phone);
          }
        })
        .finally(() => setLoading(false));
    }
  }, [profileId, initialPhone, initialRecipientLabel]);

  const filteredTemplates = templates.filter((t) => t.category === categoryTab);

  const handleSelectTemplate = (t: TemplateOption) => {
    setSelectedTemplateId(t.id);
    setMessageText(t.text);
  };

  const handleCategorySwitch = (cat: "first_time" | "follow_up") => {
    setCategoryTab(cat);
    const firstInCat = templates.find((t) => t.category === cat);
    if (firstInCat) {
      setSelectedTemplateId(firstInCat.id);
      setMessageText(firstInCat.text);
    }
  };

  const normalizeDigits = (raw: string) => {
    const d = (raw || "").replace(/\D/g, "");
    if (d.length > 10 && d.startsWith("91")) return d.slice(2);
    return d.length >= 10 ? d.slice(-10) : d;
  };

  const buildWhatsAppUrl = (useContactPicker: boolean = false) => {
    const encoded = encodeURIComponent(messageText);
    if (useContactPicker) {
      return `https://wa.me/?text=${encoded}`;
    }
    const digits = normalizeDigits(targetPhone);
    if (digits.length === 10) {
      return `https://wa.me/91${digits}?text=${encoded}`;
    }
    return `https://wa.me/?text=${encoded}`;
  };

  const handleSendWhatsApp = async (useContactPicker: boolean = false) => {
    const waUrl = buildWhatsAppUrl(useContactPicker);
    window.open(waUrl, "_blank", "noopener,noreferrer");

    if (profileId && logToTimeline) {
      const currentTpl = templates.find((t) => t.id === selectedTemplateId);
      const fd = new FormData();
      fd.append("interaction_type", "note");
      fd.append("title", `WhatsApp Sent: ${currentTpl?.stage_label || "Outreach / Follow-Up"}`);
      fd.append("raw_text", messageText);
      fd.append("visibility", "shared");
      fd.append("run_ai_update", "false");
      await apiFetch(`/api/profiles/${profileId}/interactions`, { method: "POST", body: fd }).catch(() => {});

      const patchPayload: Record<string, any> = { ball_in_court: "them" };
      if (selectedTemplateId.includes("sister_bio")) {
        patchPayload.our_biodata_sent = 1;
      }
      if (selectedTemplateId.includes("kundli")) {
        patchPayload.our_kundli_sent = 1;
      }
      await apiFetch(`/api/profiles/${profileId}`, {
        method: "PATCH",
        body: JSON.stringify(patchPayload),
      }).catch(() => {});
      onSentAndLogged?.();
    }
  };

  const handleCopy = async () => {
    await navigator.clipboard.writeText(messageText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
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
          maxWidth: 740,
          maxHeight: "90dvh",
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: "0.85rem",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.5rem" }}>
          <div>
            <div className="mono-label">
              <MessageCircle size={12} style={{ verticalAlign: "middle" }} /> 1-Tap WhatsApp Outreach &amp; Follow-Up Studio
            </div>
            <h2 style={{ fontSize: "1.3rem" }}>
              {profileId ? `Send Message / Follow-Up for ${candidateName}` : "Send Sister's Details or Follow-Up to Anyone"}
            </h2>
          </div>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            <X size={15} /> Close
          </button>
        </div>

        {loading ? (
          <div style={{ padding: "1.5rem", textAlign: "center" }}>Loading message templates...</div>
        ) : (
          <>
            {/* Step 1: First-Time Outreach vs Consecutive Follow-Up Tabs */}
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <button
                type="button"
                className={`btn btn-sm ${categoryTab === "first_time" ? "btn-primary" : ""}`}
                onClick={() => handleCategorySwitch("first_time")}
              >
                <Sparkles size={13} /> First-Time Outreach (Send Details / Intro)
              </button>
              <button
                type="button"
                className={`btn btn-sm ${categoryTab === "follow_up" ? "btn-primary" : ""}`}
                onClick={() => handleCategorySwitch("follow_up")}
              >
                <Send size={13} /> Consecutive Follow-Ups (Granular Stage Options)
              </button>
            </div>

            {/* Step 2: Granular Stage Template Pills */}
            <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
              <label className="mono-label">Select Scenario / Consecutive Stage</label>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                {filteredTemplates.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className={`btn btn-sm ${selectedTemplateId === t.id ? "btn-primary" : ""}`}
                    style={{ justifyContent: "space-between", textAlign: "left", whiteSpace: "normal" }}
                    onClick={() => handleSelectTemplate(t)}
                  >
                    <span>{t.stage_label}</span>
                    <span className="badge" style={{ marginLeft: "0.4rem" }}>
                      {t.audience}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* Step 3: Recipient Phone Selector (Saved or Any New Number) */}
            <div className="grid-2col">
              {recipients.length > 0 && (
                <div>
                  <label className="mono-label">Quick-Pick Saved Contact / Relative</label>
                  <select
                    className="select"
                    value={targetPhone}
                    onChange={(e) => setTargetPhone(e.target.value)}
                  >
                    <option value="">-- Type any phone number or pick in WhatsApp --</option>
                    {recipients.map((r, i) => (
                      <option key={i} value={r.phone}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div>
                <label className="mono-label">
                  Recipient Phone Number (Optional — Leave blank to pick any contact in WhatsApp)
                </label>
                <input
                  type="tel"
                  className="input"
                  placeholder="e.g. 9811122334 (or leave blank to choose in WhatsApp)"
                  value={targetPhone}
                  onChange={(e) => setTargetPhone(e.target.value)}
                />
              </div>
            </div>

            {/* Step 4: Editable Message Body */}
            <div>
              <label className="mono-label">Message Preview (Editable before sending)</label>
              <textarea
                className="textarea"
                rows={7}
                value={messageText}
                onChange={(e) => setMessageText(e.target.value)}
              />
            </div>

            {profileId && (
              <label style={{ display: "flex", alignItems: "center", gap: "0.45rem", fontSize: "0.84rem", fontWeight: 500 }}>
                <input
                  type="checkbox"
                  checked={logToTimeline}
                  onChange={(e) => setLogToTimeline(e.target.checked)}
                />
                Automatically log this message in {candidateName}&apos;s timeline &amp; mark Ball in Their Court
              </label>
            )}

            {/* Step 5: One-Tap Send / Copy Actions */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
              <button type="button" className="btn btn-sm" onClick={handleCopy}>
                {copied ? <Check size={14} /> : <Copy size={14} />}
                {copied ? "Copied to Clipboard ✓" : "Copy Text"}
              </button>

              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => handleSendWhatsApp(true)}
                  title="Opens WhatsApp so you can pick ANY contact or group even if their number isn't saved here"
                >
                  <ExternalLink size={14} /> Pick Any Contact in WhatsApp
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => handleSendWhatsApp(false)}
                >
                  <Send size={15} />{" "}
                  {normalizeDigits(targetPhone).length === 10
                    ? `1-Tap Send to ${normalizeDigits(targetPhone)}`
                    : "1-Tap Send on WhatsApp"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};
