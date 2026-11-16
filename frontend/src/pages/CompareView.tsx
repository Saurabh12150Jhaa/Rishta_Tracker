import React, { useEffect, useState } from "react";
import { ArrowLeft, Sparkles } from "lucide-react";
import { apiFetch, Profile } from "../api/client";

interface CompareViewProps {
  profileIds: number[];
  onBack: () => void;
  onOpenProfile: (id: number) => void;
}

export const CompareView: React.FC<CompareViewProps> = ({
  profileIds,
  onBack,
  onOpenProfile,
}) => {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [aiComp, setAiComp] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    setLoading(true);
    apiFetch<{ profiles: Profile[]; ai_comparison: any }>("/api/profiles/compare", {
      method: "POST",
      body: JSON.stringify({ profile_ids: profileIds }),
    })
      .then((res) => {
        setProfiles(res.profiles || []);
        setAiComp(res.ai_comparison || null);
      })
      .finally(() => setLoading(false));
  }, [profileIds]);

  const rows: Array<{ label: string; render: (p: Profile) => React.ReactNode }> = [
    { label: "AI Fit Score", render: (p) => (p.ai_fit_score ? `${p.ai_fit_score}%` : "—") },
    { label: "Stage / Ball", render: (p) => `${p.status} (${p.ball_in_court})` },
    { label: "Age / DOB", render: (p) => [p.age, p.dob].filter(Boolean).join(" · ") || "—" },
    { label: "Height / Diet", render: (p) => [p.height, p.diet].filter(Boolean).join(" · ") || "—" },
    { label: "Education", render: (p) => [p.education, p.college].filter(Boolean).join(" — ") || "—" },
    { label: "Occupation / Company", render: (p) => [p.occupation, p.company].filter(Boolean).join(" at ") || "—" },
    { label: "Package (CTC)", render: (p) => p.annual_ctc || "—" },
    { label: "Current City / Hometown", render: (p) => `${p.current_city || "—"} / ${p.hometown || "—"}` },
    { label: "Relocation Openness", render: (p) => p.relocation_openness || "—" },
    { label: "Gotra / Manglik", render: (p) => `${p.gotra || "—"} / ${p.manglik || "—"}` },
    { label: "Kundli Status", render: (p) => `${p.kundli_status || "Not Checked"} ${p.kundli_gunas ? `(${p.kundli_gunas})` : ""}` },
    { label: "Father / Mother", render: (p) => `${p.father_details || "—"} | ${p.mother_details || "—"}` },
    { label: "Siblings", render: (p) => p.siblings_details || "—" },
    { label: "Referred By", render: (p) => `${p.source_name || "—"} (${p.source_channel || ""})` },
    {
      label: "Family Votes",
      render: (p) =>
        (p.family_votes || []).map((v) => `${v.member_name}: ${v.vote}`).join(", ") || "No votes yet",
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
      <div className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
        <div>
          <div className="mono-label">Side-by-Side Family Discussion Table</div>
          <h1 style={{ fontSize: "1.45rem" }}>Shortlist Comparison ({profileIds.length} Candidates)</h1>
        </div>
        <button type="button" className="btn btn-sm" onClick={onBack}>
          <ArrowLeft size={14} /> Back to Dashboard
        </button>
      </div>

      {loading ? (
        <div className="card" style={{ padding: "2rem", textAlign: "center" }}>
          Running deep side-by-side comparison via <strong>claude-opus-4-6 / claude-sonnet-4-6</strong>...
        </div>
      ) : (
        <>
          {aiComp && (
            <div className="card" style={{ background: "var(--color-accent-soft)", borderColor: "var(--color-accent)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem" }}>
                <strong>
                  <Sparkles size={15} style={{ verticalAlign: "middle" }} /> AI Advisor Executive Comparison
                </strong>
                {aiComp.model_used && <span className="badge badge-indigo">{aiComp.model_used}</span>}
              </div>
              <p style={{ margin: "0 0 0.65rem", fontSize: "0.9rem" }}>{aiComp.executive_summary}</p>

              {aiComp.dimension_winners && (
                <div className="grid-2col" style={{ fontSize: "0.83rem" }}>
                  {Object.entries(aiComp.dimension_winners).map(([dim, text]) => (
                    <div key={dim} className="card" style={{ padding: "0.55rem" }}>
                      <div className="mono-label">{dim.replace(/_/g, " ")}</div>
                      <div>{String(text)}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="card" style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.86rem" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: "0.6rem", borderBottom: "2px solid var(--color-rule-strong)" }}>
                    Dimension
                  </th>
                  {profiles.map((p) => (
                    <th
                      key={p.id}
                      style={{
                        textAlign: "left",
                        padding: "0.6rem",
                        borderBottom: "2px solid var(--color-rule-strong)",
                        minWidth: 210,
                      }}
                    >
                      <button
                        type="button"
                        className="btn btn-sm btn-primary"
                        onClick={() => onOpenProfile(p.id)}
                      >
                        {p.full_name}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.label}>
                    <td
                      className="mono-label"
                      style={{
                        padding: "0.55rem 0.6rem",
                        borderBottom: "1px solid var(--color-rule)",
                        verticalAlign: "top",
                      }}
                    >
                      {r.label}
                    </td>
                    {profiles.map((p) => (
                      <td
                        key={p.id}
                        style={{
                          padding: "0.55rem 0.6rem",
                          borderBottom: "1px solid var(--color-rule)",
                          verticalAlign: "top",
                        }}
                      >
                        {r.render(p)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
};
