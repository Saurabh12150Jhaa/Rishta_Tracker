import React, { useEffect, useState } from "react";
import {
  BellRing,
  Check,
  Copy,
  Download,
  Edit3,
  MessageCircle,
  ShieldCheck,
  Smartphone,
  Sparkles,
  Trash2,
  UserPlus,
  Users,
} from "lucide-react";
import { apiFetch, Member, RelativeItem } from "../api/client";
import { WhatsAppComposerModal } from "../components/WhatsAppComposerModal";

interface SettingsSetupProps {
  member: Member;
}

export const SettingsSetup: React.FC<SettingsSetupProps> = ({ member }) => {
  const [settings, setSettings] = useState<any>(null);
  const [presets, setPresets] = useState<any>({});
  const [network, setNetwork] = useState<any>(null);
  const [relatives, setRelatives] = useState<RelativeItem[]>([]);
  const [membersList, setMembersList] = useState<Member[]>([]);

  const [excludedGotrasText, setExcludedGotrasText] = useState<string>("");
  const [citiesText, setCitiesText] = useState<string>("");
  const [dealbreakersText, setDealbreakersText] = useState<string>("");
  const [savedBanner, setSavedBanner] = useState<boolean>(false);
  const [copiedBio, setCopiedBio] = useState<boolean>(false);
  const [testingAlerts, setTestingAlerts] = useState<boolean>(false);
  const [testAlertResult, setTestAlertResult] = useState<string | null>(null);

  // Relatives Manager Form State (Add or Modify Relative)
  const [editingRelId, setEditingRelId] = useState<number | null>(null);
  const [relName, setRelName] = useState<string>("");
  const [relRelation, setRelRelation] = useState<string>("Mausi");
  const [relSide, setRelSide] = useState<string>("Maternal");
  const [relPhone, setRelPhone] = useState<string>("");
  const [relCity, setRelCity] = useState<string>("");
  const [relNotes, setRelNotes] = useState<string>("");

  // WhatsApp modal for a specific relative
  const [waRelative, setWaRelative] = useState<RelativeItem | null>(null);

  // Family Login Member Add/Edit
  const [newMemberName, setNewMemberName] = useState<string>("");
  const [newMemberPin, setNewMemberPin] = useState<string>("0000");

  // Permanent Ngrok Domain Config
  const [ngrokToken, setNgrokToken] = useState<string>("");
  const [ngrokDomain, setNgrokDomain] = useState<string>("");
  const [activatingNgrok, setActivatingNgrok] = useState<boolean>(false);
  const [ngrokStatusMsg, setNgrokStatusMsg] = useState<string | null>(null);

  const loadAll = async () => {
    const [res, relRes, memRes] = await Promise.all([
      apiFetch<any>("/api/settings"),
      apiFetch<{ relatives: RelativeItem[] }>("/api/relatives"),
      apiFetch<{ members: Member[] }>("/api/auth/members"),
    ]);
    setSettings(res.settings);
    setPresets(res.model_presets || {});
    setNetwork(res.network);
    setRelatives(relRes.relatives || []);
    setMembersList(memRes.members || []);
    const nCfg = res.settings?.ngrok_config || {};
    if (nCfg.authtoken) setNgrokToken(nCfg.authtoken);
    if (nCfg.domain) setNgrokDomain(nCfg.domain);

    const prefs = res.settings?.partner_preferences || {};
    setExcludedGotrasText((prefs.excluded_gotras || []).join(", "));
    setCitiesText((prefs.preferred_cities || []).join(", "));
    setDealbreakersText((prefs.dealbreakers || []).join(", "));
  };

  useEffect(() => {
    loadAll();
  }, []);

  if (!settings) {
    return <div className="card">Loading setup, relatives &amp; preferences...</div>;
  }

  const prefs = settings.partner_preferences || {};
  const outbound = settings.my_outbound_pack || {};
  const devices = settings.alert_devices || {
    phone_1_name: "Saurabh's Phone",
    phone_1_whatsapp: "",
    phone_1_email: "",
    phone_1_ntfy_topic: "rishta-saurabh-alerts-8f4b",
    phone_2_name: "Mummy / Sister's Phone",
    phone_2_whatsapp: "",
    phone_2_email: "",
    phone_2_ntfy_topic: "rishta-family-alerts-8f4b",
    default_reminder_minutes_before: 30,
  };
  const activePreset = settings.ai_preset || "balanced";

  const handleSaveAll = async (e: React.FormEvent) => {
    e.preventDefault();
    const updatedPrefs = {
      ...prefs,
      excluded_gotras: excludedGotrasText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      preferred_cities: citiesText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      dealbreakers: dealbreakersText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    };
    const res = await apiFetch<any>("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        ...settings,
        partner_preferences: updatedPrefs,
      }),
    });
    setSettings(res.settings);
    setSavedBanner(true);
    setTimeout(() => setSavedBanner(false), 2500);
  };

  const handleTestTwoPhoneAlerts = async () => {
    setTestingAlerts(true);
    setTestAlertResult(null);
    try {
      await apiFetch("/api/settings", {
        method: "PUT",
        body: JSON.stringify(settings),
      });
      const res = await apiFetch<any>("/api/meetings/test-phone-alerts", { method: "POST" });
      setTestAlertResult(`Alert dispatched via: ${(res.sent_channels || []).join(" + ")}`);
    } catch (err: any) {
      setTestAlertResult(`Error: ${err.message}`);
    } finally {
      setTestingAlerts(false);
    }
  };

  const handleSaveRelative = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!relName.trim()) return;
    const payload = {
      name: relName.trim(),
      relation: relRelation.trim(),
      side: relSide,
      phone: relPhone.trim(),
      city: relCity.trim(),
      notes: relNotes.trim(),
    };
    if (editingRelId) {
      await apiFetch(`/api/relatives/${editingRelId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
    } else {
      await apiFetch("/api/relatives", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    setEditingRelId(null);
    setRelName("");
    setRelPhone("");
    setRelCity("");
    setRelNotes("");
    loadAll();
  };

  const startEditRelative = (r: RelativeItem) => {
    setEditingRelId(r.id);
    setRelName(r.name);
    setRelRelation(r.relation || "Relative");
    setRelSide(r.side || "Maternal");
    setRelPhone(r.phone || "");
    setRelCity(r.city || "");
    setRelNotes(r.notes || "");
  };

  const handleDeleteRelative = async (id: number) => {
    if (!window.confirm("Remove this relative from the directory?")) return;
    await apiFetch(`/api/relatives/${id}`, { method: "DELETE" });
    loadAll();
  };

  const copyMyOutboundBio = async () => {
    await navigator.clipboard.writeText(outbound.shareable_whatsapp_bio || "");
    setCopiedBio(true);
    setTimeout(() => setCopiedBio(false), 2500);
  };

  const handleAddMember = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newMemberName.trim()) return;
    try {
      await apiFetch("/api/auth/members", {
        method: "POST",
        body: JSON.stringify({
          name: newMemberName.trim(),
          role: "family",
          pin: newMemberPin,
        }),
      });
      setNewMemberName("");
      loadAll();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleDeleteMember = async (m: Member) => {
    if (!window.confirm(`Remove login profile '${m.name}'?`)) return;
    await apiFetch(`/api/auth/members/${m.id}`, { method: "DELETE" });
    loadAll();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
      {/* Section 1: Relatives & Mediators Directory Manager (Add / Modify / 1-Tap Message) */}
      <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
        <div>
          <div className="mono-label">
            <Users size={13} style={{ verticalAlign: "middle" }} /> Relatives &amp; Mediators Directory
          </div>
          <h1 style={{ fontSize: "1.45rem" }}>Add, Modify, or 1-Tap Message Relatives &amp; Mediators</h1>
          <p style={{ margin: "0.2rem 0 0", fontSize: "0.84rem", color: "var(--color-ink-2)" }}>
            Renaming a relative or updating their phone number automatically updates all linked candidate profiles.
          </p>
        </div>

        <form onSubmit={handleSaveRelative} className="card-subtle" style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
          <div className="mono-label">
            {editingRelId ? `Editing Relative #${editingRelId}` : "+ Add New Relative or Mediator"}
          </div>
          <div className="grid-3col">
            <input
              type="text"
              className="input"
              placeholder="Name (e.g. Sunita Mausi, Khanna Bureau)"
              value={relName}
              onChange={(e) => setRelName(e.target.value)}
              required
            />
            <input
              type="text"
              className="input"
              placeholder="Relation (e.g. Mausi, Bua, Mama, Bureau)"
              value={relRelation}
              onChange={(e) => setRelRelation(e.target.value)}
            />
            <select className="select" value={relSide} onChange={(e) => setRelSide(e.target.value)}>
              <option value="Maternal">Maternal Side (Nanihal)</option>
              <option value="Paternal">Paternal Side</option>
              <option value="Family Friend">Family Friend</option>
              <option value="Mediator / Bureau">Marriage Bureau / Panditji</option>
            </select>
            <input
              type="tel"
              className="input"
              placeholder="WhatsApp Phone (10 digits)"
              value={relPhone}
              onChange={(e) => setRelPhone(e.target.value)}
            />
            <input
              type="text"
              className="input"
              placeholder="City (e.g. Delhi, Lucknow)"
              value={relCity}
              onChange={(e) => setRelCity(e.target.value)}
            />
            <input
              type="text"
              className="input"
              placeholder="Notes (e.g. Sent 3 profiles)"
              value={relNotes}
              onChange={(e) => setRelNotes(e.target.value)}
            />
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.45rem" }}>
            {editingRelId && (
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  setEditingRelId(null);
                  setRelName("");
                  setRelPhone("");
                  setRelCity("");
                  setRelNotes("");
                }}
              >
                Cancel Edit
              </button>
            )}
            <button type="submit" className="btn btn-sm btn-primary">
              <Check size={14} /> {editingRelId ? "Save Changes to Relative" : "+ Add Relative"}
            </button>
          </div>
        </form>

        {relatives.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.45rem" }}>
            {relatives.map((r) => (
              <div
                key={r.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: "0.5rem",
                  padding: "0.55rem 0.75rem",
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-rule)",
                  borderRadius: "var(--radius-sm)",
                }}
              >
                <div>
                  <strong>{r.name}</strong>{" "}
                  <span className="badge">
                    {r.relation} · {r.side}
                  </span>{" "}
                  {r.city && <span className="badge">{r.city}</span>}
                  <div style={{ fontSize: "0.8rem", color: "var(--color-ink-2)", marginTop: "0.15rem" }}>
                    Phone: {r.phone || "Not set"} · Profiles referred: {r.total_profiles || 0} (Active:{" "}
                    {r.active_profiles || 0}) {r.notes ? `· ${r.notes}` : ""}
                  </div>
                </div>

                <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    onClick={() => setWaRelative(r)}
                  >
                    <MessageCircle size={12} /> 1-Tap Send Details / Follow-Up
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => startEditRelative(r)}
                  >
                    <Edit3 size={12} /> Modify
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm"
                    data-state="error"
                    onClick={() => handleDeleteRelative(r.id)}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Section 2: 2-Phone Meeting Reminder & Alert Configuration + Preferences Form */}
      <form onSubmit={handleSaveAll} style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
            <div>
              <div className="mono-label">
                <BellRing size={13} style={{ verticalAlign: "middle" }} /> Dual-Phone Meeting Reminder &amp; Alert Setup
              </div>
              <h2 style={{ fontSize: "1.2rem" }}>Configure the 2 Phones for Scheduled Call &amp; Meeting Alerts</h2>
              <p style={{ margin: "0.2rem 0 0", fontSize: "0.83rem", color: "var(--color-ink-2)" }}>
                Install the free <strong>ntfy</strong> app on both phones and subscribe to the topic names below for
                automatic push notifications before meetings, or add WhatsApp numbers &amp; Google Calendar emails so
                both phones ring natively!
              </p>
            </div>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              data-state={testingAlerts ? "loading" : undefined}
              onClick={handleTestTwoPhoneAlerts}
            >
              <BellRing size={13} /> {testingAlerts ? "Sending Alert..." : "Send Test Alert to Both Phones"}
            </button>
          </div>

          {testAlertResult && <div className="badge badge-sage">{testAlertResult}</div>}

          <div className="grid-2col">
            <div className="card-subtle" style={{ display: "flex", flexDirection: "column", gap: "0.45rem" }}>
              <strong>Phone 1 (Saurabh&apos;s Phone)</strong>
              <div>
                <label className="mono-label">Device Label</label>
                <input
                  type="text"
                  className="input"
                  value={devices.phone_1_name || ""}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      alert_devices: { ...devices, phone_1_name: e.target.value },
                    })
                  }
                />
              </div>
              <div>
                <label className="mono-label">WhatsApp Number (10 digits)</label>
                <input
                  type="tel"
                  className="input"
                  placeholder="e.g. 9811122334"
                  value={devices.phone_1_whatsapp || ""}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      alert_devices: { ...devices, phone_1_whatsapp: e.target.value },
                    })
                  }
                />
              </div>
              <div>
                <label className="mono-label">Google Calendar Email (Auto-invited to meetings)</label>
                <input
                  type="email"
                  className="input"
                  placeholder="saurabh@gmail.com"
                  value={devices.phone_1_email || ""}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      alert_devices: { ...devices, phone_1_email: e.target.value },
                    })
                  }
                />
              </div>
              <div>
                <label className="mono-label">ntfy.sh Push Topic (Subscribe in ntfy app)</label>
                <input
                  type="text"
                  className="input"
                  value={devices.phone_1_ntfy_topic || ""}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      alert_devices: { ...devices, phone_1_ntfy_topic: e.target.value },
                    })
                  }
                />
              </div>
            </div>

            <div className="card-subtle" style={{ display: "flex", flexDirection: "column", gap: "0.45rem" }}>
              <strong>Phone 2 (Mummy / Sister&apos;s Phone)</strong>
              <div>
                <label className="mono-label">Device Label</label>
                <input
                  type="text"
                  className="input"
                  value={devices.phone_2_name || ""}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      alert_devices: { ...devices, phone_2_name: e.target.value },
                    })
                  }
                />
              </div>
              <div>
                <label className="mono-label">WhatsApp Number (10 digits)</label>
                <input
                  type="tel"
                  className="input"
                  placeholder="e.g. 9811199887"
                  value={devices.phone_2_whatsapp || ""}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      alert_devices: { ...devices, phone_2_whatsapp: e.target.value },
                    })
                  }
                />
              </div>
              <div>
                <label className="mono-label">Google Calendar Email (Auto-invited to meetings)</label>
                <input
                  type="email"
                  className="input"
                  placeholder="family@gmail.com"
                  value={devices.phone_2_email || ""}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      alert_devices: { ...devices, phone_2_email: e.target.value },
                    })
                  }
                />
              </div>
              <div>
                <label className="mono-label">ntfy.sh Push Topic (Subscribe in ntfy app)</label>
                <input
                  type="text"
                  className="input"
                  value={devices.phone_2_ntfy_topic || ""}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      alert_devices: { ...devices, phone_2_ntfy_topic: e.target.value },
                    })
                  }
                />
              </div>
            </div>
          </div>
        </div>

        {/* Sister's Outbound Pack ("What We Send to Prospect Families") */}
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
            <div>
              <div className="mono-label">Two-Way Sharing Vault</div>
              <h2 style={{ fontSize: "1.2rem" }}>Sister&apos;s Outbound Biodata &amp; Kundli Pack</h2>
            </div>
            <button type="button" className="btn btn-sm" onClick={copyMyOutboundBio}>
              <Copy size={13} /> {copiedBio ? "Copied Sister's Details ✓" : "1-Tap Copy Sister's Details"}
            </button>
          </div>

          <div className="grid-3col">
            {[
              ["my_full_name", "Sister's Full Name"],
              ["my_dob", "Sister's Date of Birth"],
              ["my_tob", "Sister's Time of Birth (for Kundli)"],
              ["my_pob", "Sister's Place of Birth"],
              ["my_gotra", "Gotra"],
              ["my_height", "Sister's Height"],
              ["my_education", "Sister's Education"],
              ["my_occupation", "Sister's Occupation & Company"],
              ["my_city", "Current City"],
            ].map(([k, label]) => (
              <div key={k}>
                <label className="mono-label">{label}</label>
                <input
                  type="text"
                  className="input"
                  value={outbound[k] || ""}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      my_outbound_pack: { ...outbound, [k]: e.target.value },
                    })
                  }
                />
              </div>
            ))}
          </div>

          <div>
            <label className="mono-label">Ready-to-Forward WhatsApp Intro &amp; Sister&apos;s Bio Text</label>
            <textarea
              className="textarea"
              rows={4}
              value={outbound.shareable_whatsapp_bio || ""}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  my_outbound_pack: { ...outbound, shareable_whatsapp_bio: e.target.value },
                })
              }
            />
          </div>
        </div>

        {/* Multi-Model Specialist Router Preset Selector + Partner Preferences */}
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
            <div>
              <div className="mono-label">
                <Sparkles size={12} style={{ verticalAlign: "middle" }} /> Zscaler zllama Multi-Model Router &amp; Preferences
              </div>
              <h2 style={{ fontSize: "1.2rem" }}>AI Specialist Model Routing &amp; Excluded Gotras</h2>
            </div>
            {savedBanner && (
              <span className="badge badge-sage">
                <Check size={13} /> Saved All Settings ✓
              </span>
            )}
          </div>

          <div className="grid-2col">
            {Object.entries(presets).map(([key, cfg]: [string, any]) => (
              <label
                key={key}
                className="card-subtle"
                style={{
                  cursor: "pointer",
                  borderColor: activePreset === key ? "var(--color-accent)" : undefined,
                  borderWidth: activePreset === key ? "2px" : "1px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", fontWeight: 700 }}>
                  <input
                    type="radio"
                    name="ai_preset"
                    checked={activePreset === key}
                    onChange={() => setSettings({ ...settings, ai_preset: key })}
                  />
                  {cfg.label}
                </div>
                <div style={{ fontSize: "0.78rem", color: "var(--color-ink-2)", marginTop: "0.4rem" }}>
                  • <strong>Biodata Vision &amp; JSON:</strong> {cfg.vision_extract_chain?.join(" → ")}
                  <br />• <strong>Hinglish Audio (.opus / Call Recording):</strong> {cfg.audio_transcribe_chain?.join(" → ")}
                  <br />• <strong>Advisor &amp; WhatsApp Replies:</strong> {cfg.reasoning_advisor_chain?.join(" → ")}
                  <br />• <strong>Embeddings (3072-dim):</strong> {cfg.embedding_chain?.join(" → ")}
                </div>
              </label>
            ))}
          </div>

          <div className="grid-2col">
            <div>
              <label className="mono-label">Excluded Gotras (Comma-separated — Triggers Clash Alert)</label>
              <input
                type="text"
                className="input"
                placeholder="e.g. Kashyap, Bharadwaj, Shandilya"
                value={excludedGotrasText}
                onChange={(e) => setExcludedGotrasText(e.target.value)}
              />
            </div>

            <div>
              <label className="mono-label">Preferred Cities (Comma-separated)</label>
              <input
                type="text"
                className="input"
                value={citiesText}
                onChange={(e) => setCitiesText(e.target.value)}
              />
            </div>

            <div>
              <label className="mono-label">Hard Dealbreakers (Comma-separated)</label>
              <input
                type="text"
                className="input"
                value={dealbreakersText}
                onChange={(e) => setDealbreakersText(e.target.value)}
              />
            </div>

            <div>
              <label className="mono-label">Diet &amp; Lifestyle Preference</label>
              <input
                type="text"
                className="input"
                value={prefs.diet_preference || ""}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    partner_preferences: { ...prefs, diet_preference: e.target.value },
                  })
                }
              />
            </div>
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <button type="submit" className="btn btn-primary">
              <Check size={15} /> Save All Settings, Phone Alerts &amp; Preferences
            </button>
          </div>
        </div>
      </form>

      {/* Android & Family Phone Connection Card */}
      <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
        <div>
          <div className="mono-label">
            <Smartphone size={13} style={{ verticalAlign: "middle" }} /> Android &amp; Family Phone Access (Works on Zscaler, 5G &amp; Wi-Fi)
          </div>
          <h2 style={{ fontSize: "1.2rem" }}>Connect Phones from Anywhere</h2>
        </div>

        {network && (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <div className="grid-2col">
              <div className="card-subtle">
                <div className="badge badge-sage" style={{ marginBottom: "0.35rem" }}>
                  Constant Local Address (mDNS — Never Changes on Home Wi-Fi)
                </div>
                <div style={{ fontWeight: 700, fontSize: "1rem", wordBreak: "break-all" }}>
                  {network.http_mdns_url}
                </div>
                <div style={{ fontSize: "0.82rem", color: "var(--color-ink-2)", marginTop: "0.2rem" }}>
                  Current LAN IP: <code>{network.http_lan_url}</code>
                </div>
              </div>

              <div className="card-subtle">
                <div className="badge badge-accent" style={{ marginBottom: "0.35rem" }}>
                  Local HTTPS (For PWA Share Sheet &amp; Live Mic)
                </div>
                <div style={{ fontWeight: 700, fontSize: "1rem", wordBreak: "break-all" }}>
                  {network.https_mdns_url}
                </div>
                <div style={{ fontSize: "0.82rem", color: "var(--color-ink-2)", marginTop: "0.2rem" }}>
                  Current LAN IP: <code>{network.https_lan_url}</code>
                </div>
                <div style={{ marginTop: "0.5rem" }}>
                  <a href="/api/setup/ca.crt" className="btn btn-sm btn-primary">
                    <Download size={13} /> Download Local Root CA (ca.crt)
                  </a>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Owner-Only: Family Login Profiles & 1-Click Backups */}
      {member.role === "owner" && (
        <div className="grid-2col">
          <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
            <div className="mono-label">Family Login Profiles (Father Removed)</div>
            <h3 style={{ fontSize: "1.1rem" }}>Manage Family Logins</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
              {membersList.map((m) => (
                <div
                  key={m.id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "0.35rem 0.55rem",
                    background: "var(--color-paper-2)",
                    borderRadius: "var(--radius-sm)",
                    fontSize: "0.85rem",
                  }}
                >
                  <span>
                    <strong>{m.name}</strong> ({m.role})
                  </span>
                  {m.name.toLowerCase() !== "saurabh" && (
                    <button
                      type="button"
                      className="btn btn-sm"
                      data-state="error"
                      onClick={() => handleDeleteMember(m)}
                    >
                      <Trash2 size={12} /> Remove
                    </button>
                  )}
                </div>
              ))}
            </div>
            <form onSubmit={handleAddMember} style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.3rem" }}>
              <input
                type="text"
                className="input"
                style={{ flex: 1 }}
                placeholder="Add Member Name (e.g. Didi)"
                value={newMemberName}
                onChange={(e) => setNewMemberName(e.target.value)}
              />
              <input
                type="text"
                className="input"
                style={{ width: 95 }}
                placeholder="PIN"
                value={newMemberPin}
                onChange={(e) => setNewMemberPin(e.target.value)}
              />
              <button type="submit" className="btn btn-sm btn-primary">
                <UserPlus size={14} /> Add
              </button>
            </form>
          </div>

          <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
            <div className="mono-label">
              <ShieldCheck size={13} style={{ verticalAlign: "middle" }} /> Local Data Sovereignty &amp; Backups
            </div>
            <h3 style={{ fontSize: "1.1rem" }}>1-Click Full Database &amp; JSON Backup</h3>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <a href="/api/backup/export-json" className="btn btn-sm btn-primary">
                <Download size={14} /> Export Full JSON Backup
              </a>
              <a href="/api/backup/export-sqlite" className="btn btn-sm">
                <Download size={14} /> Download SQLite Snapshot
              </a>
            </div>
          </div>
        </div>
      )}

      {/* 1-Tap WhatsApp Modal for Selected Relative */}
      {waRelative && (
        <WhatsAppComposerModal
          profileId={null}
          initialPhone={waRelative.phone || ""}
          initialRecipientLabel={waRelative.name}
          onClose={() => setWaRelative(null)}
        />
      )}
    </div>
  );
};
