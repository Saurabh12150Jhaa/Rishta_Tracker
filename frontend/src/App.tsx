import React, { useEffect, useState } from "react";
import {
  BookOpen,
  FilePlus2,
  Lock,
  LogOut,
  Settings,
  Smartphone,
} from "lucide-react";
import {
  apiFetch,
  getStoredToken,
  Member,
  setStoredToken,
} from "./api/client";
import { CompareView } from "./pages/CompareView";
import { Dashboard } from "./pages/Dashboard";
import { ProfileDetail } from "./pages/ProfileDetail";
import { QuickImport } from "./pages/QuickImport";
import { ReviewImport } from "./pages/ReviewImport";
import { SettingsSetup } from "./pages/SettingsSetup";

type Screen =
  | { name: "dashboard" }
  | { name: "import"; preselectedProfileId?: number | null }
  | { name: "review"; jobId: number; remainingJobIds?: number[] }
  | { name: "profile"; profileId: number }
  | { name: "compare"; profileIds: number[] }
  | { name: "settings" };

export const App: React.FC = () => {
  const [member, setMember] = useState<Member | null>(null);
  const [membersList, setMembersList] = useState<Member[]>([]);
  const [selectedLoginMember, setSelectedLoginMember] = useState<string>("Saurabh");
  const [pinInput, setPinInput] = useState<string>("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [checkingAuth, setCheckingAuth] = useState<boolean>(true);
  const [screen, setScreen] = useState<Screen>({ name: "dashboard" });
  const [workerStatus, setWorkerStatus] = useState<any>(null);

  useEffect(() => {
    if (!member) return;
    const fetchStatus = () => {
      apiFetch<any>("/api/worker/status")
        .then((s) => setWorkerStatus(s))
        .catch(() => {});
    };
    fetchStatus();
    const timer = window.setInterval(fetchStatus, 15000);
    return () => window.clearInterval(timer);
  }, [member]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const reviewJobParam = params.get("review_job");
    const tabParam = params.get("tab");
    if (reviewJobParam) {
      setScreen({ name: "review", jobId: Number(reviewJobParam) });
      window.history.replaceState({}, "", "/");
    } else if (tabParam === "import") {
      setScreen({ name: "import" });
      window.history.replaceState({}, "", "/");
    }

    Promise.all([
      apiFetch<{ members: Member[] }>("/api/auth/members").catch(() => ({ members: [] })),
      apiFetch<{ member: Member }>("/api/auth/me").catch(() => null),
    ]).then(([mRes, meRes]) => {
      setMembersList(mRes.members || []);
      if (meRes?.member) {
        setMember(meRes.member);
      }
      setCheckingAuth(false);
    });
  }, []);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError(null);
    try {
      const res = await apiFetch<{ token: string; member: Member }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ member_name: selectedLoginMember, pin: pinInput }),
      });
      setStoredToken(res.token);
      setMember(res.member);
      setPinInput("");
    } catch (err: any) {
      setLoginError(err.message || "Invalid PIN");
    }
  };

  const handleLogout = async () => {
    await apiFetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    setStoredToken(null);
    setMember(null);
  };

  if (checkingAuth) {
    return (
      <div className="main-container" style={{ paddingTop: "4rem", textAlign: "center" }}>
        Loading Rishta Dossier...
      </div>
    );
  }

  if (!member) {
    return (
      <div
        className="main-container"
        style={{
          minHeight: "92dvh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <form
          onSubmit={handleLogin}
          className="card"
          style={{
            width: "100%",
            maxWidth: 420,
            display: "flex",
            flexDirection: "column",
            gap: "1rem",
            padding: "1.75rem",
          }}
        >
          <div>
            <div className="mono-label">Private Mac-Hosted Family Workspace</div>
            <h1 style={{ fontSize: "1.65rem", marginTop: "0.2rem" }}>Sister&apos;s Rishta Dossier</h1>
            <p style={{ margin: "0.3rem 0 0", fontSize: "0.86rem", color: "var(--color-ink-2)" }}>
              Select who is using the tracker. Family members see shared profiles, kundli status, and votes; Saurabh&apos;s
              owner-only private notes stay strictly private.
            </p>
          </div>

          <div>
            <label className="mono-label" style={{ display: "block", marginBottom: "0.35rem" }}>
              Select Member Profile
            </label>
            <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
              {(membersList.length > 0
                ? membersList
                : [
                    { id: 1, name: "Saurabh", role: "owner", avatar_color: "terracotta" },
                    { id: 2, name: "Mummy", role: "family", avatar_color: "sage" },
                    { id: 3, name: "Sister", role: "family", avatar_color: "indigo" },
                  ]
              ).map((m) => (
                <button
                  key={m.name}
                  type="button"
                  className={`btn ${selectedLoginMember === m.name ? "btn-primary" : ""}`}
                  style={{ flex: 1 }}
                  onClick={() => {
                    setSelectedLoginMember(m.name);
                    setPinInput(m.role === "family" ? "0000" : "");
                  }}
                >
                  {m.name} ({m.role === "owner" ? "Owner" : "Family"})
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="mono-label" style={{ display: "block", marginBottom: "0.35rem" }}>
              Enter PIN{" "}
              <span style={{ fontWeight: 400 }}>
                (Default: Saurabh = <code>1234</code>, Mummy/Sister = <code>0000</code>)
              </span>
            </label>
            <input
              type="password"
              inputMode="numeric"
              className="input"
              placeholder="Enter 4-digit PIN..."
              value={pinInput}
              onChange={(e) => setPinInput(e.target.value)}
              autoFocus
            />
          </div>

          {loginError && (
            <div style={{ color: "var(--color-danger)", fontSize: "0.84rem", fontWeight: 600 }}>
              {loginError}
            </div>
          )}

          <button type="submit" className="btn btn-primary">
            <Lock size={15} /> Unlock Rishta Dossier
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="app-shell">
      {/* Top Bar */}
      <header className="topbar">
        <div
          style={{ display: "flex", alignItems: "center", gap: "0.6rem", cursor: "pointer" }}
          onClick={() => setScreen({ name: "dashboard" })}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: "var(--radius-sm)",
              background: "var(--color-accent)",
              color: "var(--color-surface)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: "var(--font-display)",
              fontWeight: 700,
            }}
          >
            R
          </div>
          <div>
            <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "1.05rem", lineHeight: 1.1 }}>
              Sister&apos;s Rishta Dossier
            </div>
            <div className="mono-label" style={{ fontSize: "0.66rem", display: "flex", gap: "0.45rem", alignItems: "center", flexWrap: "wrap" }}>
              <span>
                {member.name} ({member.role === "owner" ? "Owner Mode" : "Family Mode"})
              </span>
              {workerStatus && (
                <span
                  className={`badge ${workerStatus.ai_ready ? "badge-sage" : "badge-amber"}`}
                  style={{ fontSize: "0.62rem", padding: "0.08rem 0.45rem" }}
                >
                  {workerStatus.ai_ready
                    ? "Mac AI: Online ✓"
                    : `Mac Offline · Instant Parser Active (${workerStatus.pending_tasks_count || 0} queued)`}
                </span>
              )}
            </div>
          </div>
        </div>

        <nav className="desktop-nav">
          <button
            type="button"
            className={`btn btn-sm ${screen.name === "dashboard" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setScreen({ name: "dashboard" })}
          >
            <BookOpen size={14} /> Pipeline
          </button>
          <button
            type="button"
            className={`btn btn-sm ${screen.name === "import" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setScreen({ name: "import" })}
          >
            <FilePlus2 size={14} /> Quick Import
          </button>
          <button
            type="button"
            className={`btn btn-sm ${screen.name === "settings" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setScreen({ name: "settings" })}
          >
            <Smartphone size={14} /> Phone Setup &amp; Settings
          </button>
          <button type="button" className="btn btn-sm btn-ghost" onClick={handleLogout}>
            <LogOut size={14} /> Switch Member
          </button>
        </nav>
      </header>

      {/* Main Content */}
      <main className="main-container">
        {screen.name === "dashboard" && (
          <Dashboard
            member={member}
            onOpenProfile={(id) => setScreen({ name: "profile", profileId: id })}
            onOpenImport={() => setScreen({ name: "import" })}
            onOpenReviewJob={(jobId) => setScreen({ name: "review", jobId })}
            onOpenCompare={(ids) => setScreen({ name: "compare", profileIds: ids })}
          />
        )}

        {screen.name === "import" && (
          <QuickImport
            preselectedProfileId={screen.preselectedProfileId}
            onJobCreated={(jobIds) => {
              if (jobIds.length > 0) {
                setScreen({
                  name: "review",
                  jobId: jobIds[0],
                  remainingJobIds: jobIds.slice(1),
                });
              } else {
                setScreen({ name: "dashboard" });
              }
            }}
          />
        )}

        {screen.name === "review" && (
          <ReviewImport
            jobId={screen.jobId}
            onSelectOtherJob={(otherId) =>
              setScreen({ name: "review", jobId: otherId, remainingJobIds: screen.remainingJobIds })
            }
            onApplied={(profileId) => {
              const rem = (screen.remainingJobIds || []).filter((id) => id !== screen.jobId);
              if (rem.length > 0) {
                setScreen({ name: "review", jobId: rem[0], remainingJobIds: rem.slice(1) });
              } else {
                setScreen({ name: "profile", profileId });
              }
            }}
            onCancel={() => {
              const rem = (screen.remainingJobIds || []).filter((id) => id !== screen.jobId);
              if (rem.length > 0) {
                setScreen({ name: "review", jobId: rem[0], remainingJobIds: rem.slice(1) });
              } else {
                setScreen({ name: "dashboard" });
              }
            }}
          />
        )}

        {screen.name === "profile" && (
          <ProfileDetail
            profileId={screen.profileId}
            member={member}
            onBack={() => setScreen({ name: "dashboard" })}
            onAddMoreMedia={(pid) => setScreen({ name: "import", preselectedProfileId: pid })}
          />
        )}

        {screen.name === "compare" && (
          <CompareView
            profileIds={screen.profileIds}
            onBack={() => setScreen({ name: "dashboard" })}
            onOpenProfile={(id) => setScreen({ name: "profile", profileId: id })}
          />
        )}

        {screen.name === "settings" && <SettingsSetup member={member} />}
      </main>

      {/* Mobile Bottom Navigation */}
      <nav className="bottom-nav">
        <button
          type="button"
          className={`bottom-nav-btn ${screen.name === "dashboard" ? "active" : ""}`}
          onClick={() => setScreen({ name: "dashboard" })}
        >
          <BookOpen size={18} />
          <span>Pipeline</span>
        </button>
        <button
          type="button"
          className={`bottom-nav-btn ${screen.name === "import" ? "active" : ""}`}
          onClick={() => setScreen({ name: "import" })}
        >
          <FilePlus2 size={18} />
          <span>Quick Import</span>
        </button>
        <button
          type="button"
          className={`bottom-nav-btn ${screen.name === "settings" ? "active" : ""}`}
          onClick={() => setScreen({ name: "settings" })}
        >
          <Settings size={18} />
          <span>Phone &amp; AI</span>
        </button>
        <button type="button" className="bottom-nav-btn" onClick={handleLogout}>
          <LogOut size={18} />
          <span>{member.name}</span>
        </button>
      </nav>
    </div>
  );
};
