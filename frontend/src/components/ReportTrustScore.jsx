import React from "react";

/**
 * Resolve display trust the same way as the reports list API / stats dashboard:
 * report.trust_score when present, else latest ML prediction trust_score.
 */
export function resolveReportTrustScore(report) {
  if (!report) return null;
  if (report.trust_score !== null && report.trust_score !== undefined && report.trust_score !== "") {
    const n = parseFloat(report.trust_score);
    if (Number.isFinite(n)) return n;
  }
  const preds = report.ml_predictions;
  if (Array.isArray(preds) && preds.length > 0) {
    const latest = preds.reduce((best, pred) => {
      if (!pred) return best;
      if (!best) return pred;
      const a = pred.evaluated_at ? new Date(pred.evaluated_at).getTime() : 0;
      const b = best.evaluated_at ? new Date(best.evaluated_at).getTime() : 0;
      return a > b ? pred : best;
    }, null);
    if (latest?.trust_score != null && latest.trust_score !== undefined) {
      const n = parseFloat(latest.trust_score);
      if (Number.isFinite(n)) return n;
    }
  }
  return null;
}

export function trustScoreBarColor(score) {
  const n = Number(score);
  if (n >= 70) return "var(--success)";
  if (n >= 40) return "var(--warning)";
  return "var(--danger)";
}

/**
 * Trust bar used on Reports list and Report detail — reuse on dashboard recent reports.
 */
export default function ReportTrustScore({ report, trustScore: trustScoreProp }) {
  const raw = trustScoreProp !== undefined ? trustScoreProp : resolveReportTrustScore(report);
  if (raw === null || raw === undefined || !Number.isFinite(Number(raw))) {
    return (
      <span style={{ fontSize: 11, color: "var(--muted)", fontWeight: 600 }}>—</span>
    );
  }

  const score = Number(raw);
  const width = Math.max(0, Math.min(100, score));

  return (
    <div className="trust-wrap">
      <div className="trust-track">
        <div
          className="trust-fill"
          style={{
            width: `${width}%`,
            background: trustScoreBarColor(score),
          }}
        />
      </div>
      <div className="trust-val">{Math.round(score)}</div>
    </div>
  );
}
