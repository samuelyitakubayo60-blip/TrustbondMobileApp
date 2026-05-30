import React from "react";
import {
  formatOperationalPipelineLabel,
  operationalPipelineBadgeClass,
  formatOperationalPipelineHint,
  operationalGateChecklist,
} from "../utils/reportOperationalLabels";

/**
 * Visual summary of the two-gate report pipeline (AI → leader → cases/hotspots).
 */
export default function ReportWorkflowBanner({ report, compact = false }) {
  if (!report) return null;

  const gates = operationalGateChecklist(report);
  const label = formatOperationalPipelineLabel(report);
  const badge = operationalPipelineBadgeClass(report);
  const hint = formatOperationalPipelineHint(report);

  if (compact) {
    return (
      <div
        className="alert"
        style={{
          marginBottom: 14,
          background: "rgba(59, 130, 246, 0.06)",
          border: "1px solid rgba(59, 130, 246, 0.25)",
          padding: "12px 14px",
        }}
      >
        <span className={`badge ${badge}`} style={{ marginRight: 8 }}>
          {label}
        </span>
        <span style={{ fontSize: 13, lineHeight: 1.45 }}>{hint}</span>
      </div>
    );
  }

  return (
    <div
      className="card"
      style={{
        marginBottom: 16,
        border: "1px solid var(--border2)",
        background: "var(--surface2)",
      }}
    >
      <div className="card-header" style={{ paddingBottom: 8 }}>
        <div className="card-title">Report workflow</div>
        <span className={`badge ${badge}`}>{label}</span>
      </div>
      <div style={{ padding: "0 14px 14px", fontSize: 12, lineHeight: 1.5 }}>
        <p style={{ margin: "0 0 12px", color: "var(--muted)" }}>{hint}</p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            gap: 10,
          }}
        >
          {gates.map((g) => (
            <div
              key={g.key}
              style={{
                padding: "10px 12px",
                borderRadius: 8,
                border: `1px solid ${g.done ? "rgba(61, 190, 133, 0.4)" : "var(--border2)"}`,
                background: g.done ? "rgba(61, 190, 133, 0.08)" : "var(--card)",
              }}
            >
              <div style={{ fontWeight: 700, marginBottom: 4, fontSize: 11 }}>
                {g.done ? "✓ " : "○ "}
                {g.label}
              </div>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>{g.detail}</div>
            </div>
          ))}
        </div>
        <div
          style={{
            marginTop: 12,
            fontSize: 11,
            color: "var(--muted)",
            paddingTop: 10,
            borderTop: "1px solid var(--border2)",
          }}
        >
          Citizen submit → AI threshold/rules → local leader confirms →
          cases & hotspot clusters only when both verification gates pass.
        </div>
      </div>
    </div>
  );
}
