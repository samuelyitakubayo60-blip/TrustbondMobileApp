import React, { useEffect, useState } from "react";
import api from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { formatLocalDateTime } from "../../utils/dateTime";
import {
  formatTechnicalStatus,
  formatCommunityConfirmation,
  formatHotspotClusteringCue,
  communityBadgeClass,
  formatOperationalPipelineLabel,
  operationalPipelineBadgeClass,
} from "../../utils/reportOperationalLabels";
import ReportWorkflowBanner from "../ReportWorkflowBanner";
import {
  hasDescriptionCredibility,
  descriptionCredibilityDetailLines,
} from "../../utils/descriptionCredibility";

const friendlyFlagReason = (reason) => {
  const m = {
    evidence_time_mismatch:
      "Evidence was captured too long before the report was submitted.",
    stale_live_capture_timestamp:
      "Live-capture evidence timestamp appears stale.",
    incident_description_mismatch:
      "Description appears inconsistent with the selected incident type.",
    incident_text_mismatch:
      "Description appears inconsistent with the selected incident type.",
    INCIDENT_TEXT_MISMATCH:
      "Description appears inconsistent with the selected incident type.",
    description_evidence_mismatch:
      "Description, media, and incident type do not align.",
    evidence_incident_mismatch:
      "Uploaded media does not support the selected incident type.",
    threshold_low_score:
      "Automated credibility score was too low to auto-confirm.",
    gibberish_description:
      "Description looks meaningless or spammy and needs manual review.",
    ai_suspicious_review:
      "AI marked this report as suspicious and requires human review.",
    ai_uncertain_review: "AI result is uncertain and requires manual review.",
    ai_detected_fake: "AI detected possible fake/manipulated evidence.",
    device_burst_reporting:
      "Device submitted too many reports in a short period.",
    duplicate_description_recent:
      "Description was repeatedly submitted from the same device.",
    no_description_with_evidence:
      "Evidence was uploaded without enough description context.",
    minimal_description: "Description is too short for reliable triage.",
    high_severity_incident:
      "High-severity incident automatically requires manual review.",
  };
  if (!reason) return "";
  return m[reason] || reason.replaceAll("_", " ");
};

const normalizePercent = (value) => {
  if (value == null) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return n <= 1 ? n * 100 : n;
};

const formatCoords = (lat, lon) => {
  const nLat = Number(lat);
  const nLon = Number(lon);
  if (!Number.isFinite(nLat) || !Number.isFinite(nLon)) return "—";
  return `${nLat.toFixed(6)}, ${nLon.toFixed(6)}`;
};

const friendlyPredictionLabel = (label) => {
  const key = String(label || "").trim().toLowerCase();
  if (!key) return "—";
  const map = {
    likely_real: "Likely real",
    suspicious: "Suspicious",
    uncertain: "Uncertain",
    fake: "Likely fake",
    real: "Likely real",
  };
  return map[key] || key.replace(/_/g, " ");
};

const cleanAiNarrative = (text) => {
  const raw = String(text || "").trim();
  if (!raw) return "";
  const stopMarkers = [
    "Decision patterns:",
    "Pattern explanations:",
    "AI scoring breakdown:",
    "ML label:",
    "Rule status:",
    "WHAT THE CITIZEN REPORTED",
    "AUTOMATED OUTCOME",
    "WHY THE SYSTEM REACHED",
  ];
  let cleaned = raw;
  for (const marker of stopMarkers) {
    const idx = cleaned.indexOf(marker);
    if (idx >= 0) cleaned = cleaned.slice(0, idx).trim();
  }
  return cleaned
    .replace(/^AI verification result:\s*/i, "")
    .replace(/^Report context:\s*/i, "")
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join("\n\n")
    .trim();
};

const descriptionCredibilityPanelStyle = {
  padding: "10px 12px",
  borderRadius: 8,
  background: "rgba(156, 39, 176, 0.08)",
  border: "1px solid rgba(156, 39, 176, 0.28)",
  color: "var(--text)",
  fontSize: 12,
  display: "grid",
  gap: 8,
};

function DescriptionCredibilityPanel({ report, title }) {
  if (!hasDescriptionCredibility(report)) return null;
  const lines = descriptionCredibilityDetailLines(report);
  const summary = (report.credibility_summary || "").trim();
  return (
    <div style={descriptionCredibilityPanelStyle}>
      <div style={{ fontWeight: 700 }}>{title}</div>
      {summary ? (
        <div style={{ lineHeight: 1.5 }}>{summary}</div>
      ) : null}
      {lines.length > 0 ? (
        <ul
          style={{
            margin: 0,
            paddingLeft: 18,
            lineHeight: 1.45,
            fontSize: 11,
            color: "var(--muted)",
          }}
        >
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

const prettyFactorName = (key) => {
  if (key === "aggregation_adjustment") {
    return "Policy / aggregation adjustment";
  }
  return String(key || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
};

const friendlyPatternChipLabel = (code, explanations) => {
  const key = String(code || "").trim();
  const exp =
    explanations && typeof explanations === "object"
      ? explanations[key] || explanations[key.toUpperCase()]
      : "";
  if (exp && typeof exp === "string") {
    const plain = exp.includes(": ") ? exp.split(": ").slice(1).join(": ").trim() : exp;
    if (plain.length > 0 && plain.length <= 120) return plain;
    if (plain.length > 120) return `${plain.slice(0, 117)}…`;
  }
  return key.replace(/_/g, " ").toLowerCase();
};

const renderDecisionPatternChips = (patterns, explanations) => {
  if (!Array.isArray(patterns) || patterns.length === 0) return null;
  const patternTone = (pattern) => {
    const p = String(pattern || "").toUpperCase();
    if (
      p.includes("FINAL_REJECTED") ||
      p.includes("RULE_REJECTION") ||
      p.includes("LOW_TRUST") ||
      p.includes("TAMPERED") ||
      p.includes("INVALID_EVIDENCE") ||
      p.includes("SCREENSHOT")
    ) {
      return { bg: "var(--surface2)", border: "var(--border2)", text: "var(--danger)" };
    }
    if (
      p.includes("PENDING") ||
      p.includes("FLAGGED") ||
      p.includes("MISMATCH") ||
      p.includes("CONFLICT") ||
      p.includes("UNCLEAR")
    ) {
      return { bg: "var(--surface2)", border: "var(--border2)", text: "var(--warning)" };
    }
    if (
      p.includes("FINAL_CONFIRMED") ||
      p.includes("RULES_PASSED") ||
      p.includes("HIGH_TRUST") ||
      p.includes("HUMAN_CONFIRMED")
    ) {
      return { bg: "var(--surface2)", border: "var(--border2)", text: "var(--success)" };
    }
    return { bg: "var(--surface2)", border: "var(--border2)", text: "var(--text)" };
  };
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
      {patterns.map((p) => {
        const tone = patternTone(p);
        return (
          <span
            key={p}
            style={{
              fontSize: 10,
              cursor: "help",
              padding: "4px 8px",
              borderRadius: 999,
              border: `1px solid ${tone.border}`,
              background: tone.bg,
              color: tone.text,
              fontWeight: 700,
              letterSpacing: 0.2,
            }}
            title={p}
          >
            {friendlyPatternChipLabel(p, explanations)}
          </span>
        );
      })}
    </div>
  );
};

const relativeTime = (isoLike) => {
  if (!isoLike) return null;
  const t = new Date(isoLike);
  if (Number.isNaN(t.getTime())) return null;
  const now = new Date();
  const hours = (now - t) / (1000 * 60 * 60);
  if (hours < 1) return "Active now";
  if (hours < 24) return `${Math.round(hours)}h ago`;
  if (hours < 24 * 7) return `${Math.round(hours / 24)}d ago`;
  return `${Math.round(hours / (24 * 7))}w ago`;
};

// Verification helper functions

/**
 * Workflow:
 *   verified  (trust ≥ 70) → auto-verified + auto-confirmed (no leader needed)
 *   under_review (45-70)   → only a local leader can confirm
 *   rejected  (< threshold) → auto-rejected (no leader needed)
 */
const isReportVerified = (report) => {
  const vs = (report.verification_status || "").toLowerCase();
  return vs === "verified";
};

const isReportRejected = (report) => {
  const vs = (report.verification_status || "").toLowerCase();
  const rs = (report.rule_status || "").toLowerCase();
  return vs === "rejected" || rs === "rejected";
};

const isReportUnderReview = (report) => {
  if (isReportVerified(report) || isReportRejected(report)) return false;
  const vs = (report.verification_status || "").toLowerCase();
  return vs === "under_review" || vs === "pending" || vs === "";
};

const getVerificationStatus = (report) => {
  if (isReportVerified(report)) {
    return (
      <span style={{ fontSize: "11px", color: "var(--success)", fontWeight: 600 }}>
        Auto-verified by AI
      </span>
    );
  }
  if (isReportRejected(report)) {
    return (
      <span style={{ fontSize: "11px", color: "var(--danger)", fontWeight: 600 }}>
        Auto-rejected by AI
      </span>
    );
  }
  // under_review / pending
  const leaderStatus = (report.leader_verification_status || "").toLowerCase();
  if (leaderStatus === "confirmed") {
    return (
      <span style={{ fontSize: "11px", color: "var(--success)", fontWeight: 600 }}>
        Confirmed by local leader
      </span>
    );
  }
  return (
    <span style={{ fontSize: "11px", color: "var(--warning)", fontWeight: 600 }}>
      Under review — awaiting local leader
    </span>
  );
};

const getLeaderReviewStatus = (report) => {
  const leaderStatus = (report.leader_verification_status || "").toLowerCase();
  const leaderSubmitted = report.submitted_by_local_leader_id != null && report.submitted_by_local_leader_id !== "";

  if (leaderSubmitted) {
    return {
      text: "Submitted by local leader — auto-confirmed",
      color: "var(--success)",
    };
  }
  if (isReportVerified(report)) {
    return {
      text: "Auto-confirmed (AI verified with high confidence)",
      color: "var(--success)",
    };
  }
  if (isReportRejected(report)) {
    return {
      text: "Not required — report was auto-rejected",
      color: "var(--muted)",
    };
  }
  // under_review — leader is the one who decides
  if (leaderStatus === "confirmed") {
    return {
      text: "Confirmed by local leader",
      color: "var(--success)",
    };
  }
  if (leaderStatus === "rejected") {
    return {
      text: "Rejected by local leader",
      color: "var(--danger)",
    };
  }
  return {
    text: "Awaiting local leader verification",
    color: "var(--warning)",
  };
};

const ReportDetail = ({ goToScreen, openModal, reportId, wsRefreshKey }) => {
  const { user: me } = useAuth();
  const role = me?.role || "officer";

  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [mlPrediction, setMlPrediction] = useState(null);
  const [mlLoading, setMlLoading] = useState(false);
  const [relatedReports, setRelatedReports] = useState([]);
  const [relatedLoading, setRelatedLoading] = useState(false);
  const [showLinkCaseModal, setShowLinkCaseModal] = useState(false);
  const [availableCases, setAvailableCases] = useState([]);
  const [casesLoading, setCasesLoading] = useState(false);
  const [selectedCase, setSelectedCase] = useState("");
  const [caseSearch, setCaseSearch] = useState("");
  const [linkingCase, setLinkingCase] = useState(false);
  const [reportCase, setReportCase] = useState(null);
  const [caseLoading, setCaseLoading] = useState(false);
  const [locationHistory, setLocationHistory] = useState(null);
  const [locationLoading, setLocationLoading] = useState(false);

  useEffect(() => {
    if (!reportId) {
      setError("No report selected.");
      setLoading(false);
      return;
    }
    let mounted = true;
    setLoading(true);

    const fetchReportData = () => {
      api
        .get(`/api/v1/reports/${reportId}`)
        .then((res) => {
          if (!mounted) return;
          setReport(res);
          setLoading(false);
        })
        .catch((err) => {
          if (!mounted) return;
          setError(
            err?.data?.detail || err?.message || "Failed to load report.",
          );
          setLoading(false);
        });
    };

    fetchReportData();

    return () => {
      mounted = false;
    };
  }, [reportId, wsRefreshKey]);

  // Load ML prediction for this report
  useEffect(() => {
    if (!report || !report.report_id || !report.device_id) return;
    let cancelled = false;
    setMlLoading(true);
    api
      .get(
        `/api/v1/devices/reports/${report.report_id}/prediction?device_id=${report.device_id}`,
      )
      .then((res) => {
        if (cancelled) return;
        setMlPrediction(res);
      })
      .catch((error) => {
        if (cancelled) return;
        console.log("ML prediction not available for this report:", error.message);
        setMlPrediction(null);
      })
      .finally(() => {
        if (!cancelled) setMlLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [report?.report_id]);

  const loadReportCase = async () => {
    if (!report?.case_id) {
      setReportCase(null);
      return;
    }
    
    setCaseLoading(true);
    try {
      const caseData = await api.get(`/api/v1/cases/${report.case_id}`);
      setReportCase(caseData);
    } catch (e) {
      console.error("Failed to load case details:", e);
      setReportCase(null);
    } finally {
      setCaseLoading(false);
    }
  };

  const loadLocationHistory = async () => {
    if (!report?.report_id) return;
    
    setLocationLoading(true);
    try {
      const response = await api.get(`/api/v1/reports/${report.report_id}/location-history`);
      setLocationHistory(response);
    } catch (e) {
      console.error("Failed to load location history:", e);
      setLocationHistory(null);
    } finally {
      setLocationLoading(false);
    }
  };

  useEffect(() => {
    loadReportCase();
  }, [report?.case_id]);

  useEffect(() => {
    loadLocationHistory();
  }, [report?.report_id]);

  // Load related reports
  useEffect(() => {
    if (!report || !report.report_id) return;
    let cancelled = false;
    setRelatedLoading(true);
    api
      .get(`/api/v1/reports/${report.report_id}/related`)
      .then((res) => {
        if (cancelled) return;
        setRelatedReports(res || []);
      })
      .catch(() => {
        if (cancelled) return;
        setRelatedReports([]);
      })
      .finally(() => {
        if (!cancelled) setRelatedLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [report]);

  if (loading) {
    return (
      <div>
        <div style={{ marginBottom: "4px" }}>Loading...</div>
      </div>
    );
  }

  const refreshInBackground = async () => {
    if (!reportId) return;
    try {
      const res = await api.get(`/api/v1/reports/${reportId}`);
      setReport(res);
    } catch {
      // Keep optimistic UI if background refresh fails.
    }
  };

  const loadAvailableCases = async () => {
    setCasesLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (caseSearch) {
        params.append('search', caseSearch);
      }
      // Only show cases with the same incident type
      if (report?.incident_type_id) {
        params.append('incident_type_id', report.incident_type_id);
      }
      params.append('limit', '50');
      
      const response = await api.get(`/api/v1/cases/?${params}`);
      let cases = Array.isArray(response) ? response : (response?.items || []);
      
      // Additional client-side filtering to ensure incident type match
      if (report?.incident_type_id) {
        cases = cases.filter(case_item => case_item.incident_type_id === report.incident_type_id);
      }
      
      // Exclude the current case if report is already linked (for move functionality)
      if (report?.case_id) {
        cases = cases.filter(case_item => case_item.case_id !== report.case_id);
      }
      
      setAvailableCases(cases);
    } catch (e) {
      setError(e?.message || "Failed to load cases");
      setAvailableCases([]);
    } finally {
      setCasesLoading(false);
    }
  };

  const openLinkCaseModal = () => {
    setShowLinkCaseModal(true);
    setSelectedCase("");
    setCaseSearch("");
    loadAvailableCases();
  };

  const linkReportToCase = async () => {
    if (!selectedCase || !reportId) return;
    
    setLinkingCase(true);
    setError("");
    setActionMessage("");
    
    try {
      // If report is already in a case, move it. Otherwise, add it.
      if (report.case_id) {
        await api.post(`/api/v1/cases/reports/${reportId}/move`, {
          target_case_id: selectedCase
        });
        setActionMessage("Report moved to different case successfully");
      } else {
        await api.post(`/api/v1/cases/${selectedCase}/reports`, {
          report_ids: [reportId]
        });
        setActionMessage("Report linked to case successfully");
      }

      // Update report data
      setReport(prev => ({
        ...prev,
        case_id: selectedCase
      }));

      setShowLinkCaseModal(false);
      setSelectedCase("");
      refreshInBackground();
    } catch (e) {
      let errorMessage = e?.message || "Failed to link report to case";
      
      // Provide more user-friendly error messages
      if (errorMessage.includes("incident type mismatch")) {
        errorMessage = "Cannot link to this case: Incident types do not match. Reports can only be linked to cases with the same incident type.";
      } else if (errorMessage.includes("already linked to another case")) {
        errorMessage = "This report is already linked to a case. Use the Move to different case option instead.";
      } else if (errorMessage.includes("Access denied")) {
        errorMessage = "You do not have permission to link to this case.";
      }
      
      setError(errorMessage);
    } finally {
      setLinkingCase(false);
    }
  };

  const unlinkReportFromCase = async () => {
    if (!report.case_id || !reportId) return;
    
    if (!window.confirm("Are you sure you want to unlink this report from its case?")) {
      return;
    }
    
    setLinkingCase(true);
    setError("");
    setActionMessage("");
    
    try {
      await api.delete(`/api/v1/cases/${report.case_id}/reports/${reportId}`);
      
      setReport(prev => ({
        ...prev,
        case_id: null
      }));
      
      setReportCase(null);

      setActionMessage("Report unlinked from case successfully");
      refreshInBackground();
    } catch (e) {
      setError(e?.message || "Failed to unlink report from case");
    } finally {
      setLinkingCase(false);
    }
  };

  if (error || !report) {
    return (
      <div style={{ padding: 16 }}>
        <button
          className="btn btn-outline btn-sm"
          onClick={() => goToScreen("reports", 1)}
        >
          Back to Reports
        </button>
        <div style={{ marginTop: 12, color: "var(--danger)", fontSize: 13 }}>
          {error || "Report not found."}
        </div>
      </div>
    );
  }

  const idLabel = report.report_number || String(report.report_id).slice(0, 8);
  const deviceShort = report.device_id
    ? String(report.device_id).slice(0, 4)
    : "DEV";
  const trustScore = Number(report.trust_score ?? mlPrediction?.trust_score ?? 0);
  const trustFactors = report.trust_factors || {};
  const communityVotes = report.community_votes || { real: 0, false: 0, unknown: 0 };
  const realVotes = Number(communityVotes.real || 0);
  const falseVotes = Number(communityVotes.false || 0);
  const unknownVotes = Number(communityVotes.unknown || 0);
  const totalVotes = realVotes + falseVotes + unknownVotes;
  const createdAt = formatLocalDateTime(report.reported_at);
  const assignments = report.assignments || [];
  const hasCase = report.case_id; // Assuming case_id is available
  const locationHierarchy = [
    report.incident_sector_name || report.sector_name,
    report.incident_cell_name || report.cell_name,
    report.incident_village_name || report.village_name,
  ]
    .filter(Boolean)
    .join(" > ");
  const coordsText = formatCoords(report.latitude, report.longitude);

  // Status configuration
  const getStatusConfig = (status) => {
    const configs = {
      pending: { color: "b-yellow", text: "Pending Review" },
      under_review: { color: "b-yellow", text: "Pending Review" },
      passed: { color: "b-green", text: "AI Verified" }, // AI-verified reports
      verified: { color: "b-green", text: "Verified" },
      flagged: { color: "b-orange", text: "Needs Review" }, // Medium confidence
      rejected: { color: "b-red", text: "Rejected" },
    };
    return configs[status] || { color: "b-gray", text: "Unknown" };
  };

  const statusConfig = getStatusConfig(report.status || report.rule_status || "pending");

  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "10px",
          marginBottom: "16px",
          flexWrap: "wrap",
        }}
      >
        <button
          className="btn btn-outline btn-sm"
          onClick={() => goToScreen("reports", 1)}
        >
          Back to Reports
        </button>
        <div
          style={{
            fontFamily: '"Syne", sans-serif',
            fontWeight: 800,
            fontSize: "18px",
          }}
        >
          {report.incident_type_name || idLabel}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span className={`badge ${operationalPipelineBadgeClass(report)}`}>
            {formatOperationalPipelineLabel(report)}
          </span>
          {hasCase && (
            <span
              className="badge b-blue"
              style={{ fontSize: "12px", padding: "4px 8px" }}
            >
              Linked to case
            </span>
          )}
        </div>
        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            gap: "6px",
            flexWrap: "wrap",
          }}
        >
          {hasCase && (
            <button
              className="btn btn-info btn-sm"
              onClick={() => goToScreen("case-detail", report.case_id)}
              style={{ display: "flex", alignItems: "center", gap: 4 }}
            >
              View case
            </button>
          )}
        </div>
      </div>

      {actionMessage && (
        <div
          style={{
            marginBottom: 12,
            padding: "10px 12px",
            borderRadius: 8,
            background: "var(--surface2)",
            border: "1px solid var(--border2)",
            color: "var(--text)",
            fontSize: 12,
          }}
        >
          {actionMessage}
        </div>
      )}

      <ReportWorkflowBanner report={report} />

      <div className="detail-layout">
        <div className="detail-col">
          <div className="card">
            <div className="card-header">
              <div className="card-title">Incident Details</div>
            </div>
            {report.flag_reason && (
              <div
                style={{
                  margin: "0 14px 12px",
                  padding: "10px 12px",
                  borderRadius: 8,
                  background: "var(--surface2)",
                  border: "1px solid var(--border2)",
                  color: "var(--text)",
                  fontSize: 12,
                }}
              >
                <strong>Review reason:</strong>{" "}
                {friendlyFlagReason(report.flag_reason)}
              </div>
            )}
            {(report.ai_verification_reason ||
              hasDescriptionCredibility(report)) && (
              <div
                style={{
                  margin: "0 14px 12px",
                  padding: "10px 12px",
                  borderRadius: 8,
                  background: "var(--surface2)",
                  border: "1px solid var(--border2)",
                  color: "var(--text)",
                  fontSize: 12,
                  display: "grid",
                  gap: 8,
                }}
              >
                {report.ai_verification_reason && (
                  <div style={{ lineHeight: 1.65, whiteSpace: "pre-wrap" }}>
                    <strong>Automated screening summary</strong>
                    <div style={{ marginTop: 6 }}>
                      {cleanAiNarrative(report.ai_verification_reason)}
                    </div>
                  </div>
                )}
                {hasDescriptionCredibility(report) && (
                  <DescriptionCredibilityPanel
                    report={report}
                    title="Credibility score details"
                  />
                )}
              </div>
            )}
            <div className="detail-grid">
              <div className="detail-field">
                <div className="dfl">Incident Type</div>
                <div className="dfv" style={{ color: "var(--danger)" }}>
                  {report.incident_type_name || "—"}
                </div>
              </div>
              <div className="detail-field">
                <div className="dfl">Location</div>
                <div className="dfv">
                  {locationHierarchy || "—"}
                </div>
              </div>
              <div className="detail-field">
                <div className="dfl">Submitted At</div>
                <div className="dfv" style={{ fontSize: "12px" }}>
                  {createdAt}
                </div>
              </div>
            </div>
            <div
              style={{
                background: "var(--surface2)",
                borderRadius: "var(--rs)",
                padding: "11px",
                border: "1px solid var(--border2)",
              }}
            >
              <div
                style={{
                  fontSize: "10px",
                  color: "var(--muted)",
                  marginBottom: "5px",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.5px",
                }}
              >
                Description
              </div>
              <div style={{ fontSize: "12px", lineHeight: 1.6 }}>
                {report.description || "No description."}
              </div>
            </div>
          </div>

          {/* ── Incident Location Card ── */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">Incident Location</div>
            </div>
            <div style={{ padding: "14px 16px", fontSize: 12 }}>
              {/* Primary: Administrative location */}
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 10, color: "var(--muted)", fontWeight: 700, textTransform: "uppercase", marginBottom: 4, letterSpacing: "0.5px" }}>
                  Reported Area
                </div>
                <div style={{ fontWeight: 700, fontSize: 15, color: "var(--text)" }}>
                  {[report.incident_sector_name || report.sector_name, report.incident_cell_name || report.cell_name, report.incident_village_name || report.village_name].filter(Boolean).join("  >  ") || "Location not specified"}
                </div>
              </div>

              {/* Location precision and reporter status */}
              <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
                {report.gps_accuracy != null && (() => {
                  const acc = Number(report.gps_accuracy);
                  const label = acc <= 10 ? "High Precision" : acc <= 30 ? "Good Precision" : "Low Precision";
                  const badgeClass = acc <= 10 ? "b-green" : acc <= 30 ? "b-orange" : "b-red";
                  return (
                    <span className={`badge ${badgeClass}`} style={{ fontSize: 11 }}>
                      {label}
                    </span>
                  );
                })()}

              </div>

              {/* GPS coordinates - subtle, not the focus */}
              {coordsText && coordsText !== "—" && (
                <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 12 }}>
                  GPS: {coordsText}
                </div>
              )}

              {/* Action buttons */}
              {report.latitude && report.longitude && (
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => goToScreen("safety-map", 0, { focusCoords: { lat: report.latitude, lon: report.longitude } })}
                    style={{ fontSize: 11 }}
                  >
                    View on Map
                  </button>
                  <button
                    className="btn btn-outline btn-sm"
                    onClick={() => window.open(`https://www.google.com/maps/dir/?api=1&destination=${report.latitude},${report.longitude}&travelmode=driving`, '_blank')}
                    style={{ fontSize: 11 }}
                  >
                    Navigate to Location
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* ── Report Credibility Analysis Card ── */}
          {report.verification_pipeline && (() => {
            const vp = report.verification_pipeline;
            const ts = vp.trust_score || {};
            const overallScore = ts.trust_score ?? 0;
            const overallColor = overallScore >= 70 ? "var(--success)" : overallScore >= 45 ? "var(--warning)" : "var(--danger)";
            const overallBg = "var(--surface2)";
            const overallBorder = "var(--border2)";
            const verdictText = overallScore >= 70
              ? "This report has been verified as credible"
              : overallScore >= 45
              ? "This report needs further review"
              : "This report was flagged as unreliable";

            /* Helper: friendly name map for trust score components */
            const friendlyNames = {
              incident_match: "Description Match",
              description_quality: "Description Quality",
              evidence_match: "Evidence Review",
              evidence_admissibility: "Evidence Validity",
              location_consistency: "Location Credibility",
              reporter_history: "Reporter Reliability",
            };

            const comps = (ts.components || []).filter(c => c.available);
            const totalWeight = comps.reduce((sum, c) => sum + (c.weight ?? 0), 0);

            return (
            <div className="card">
              <div className="card-header">
                <div className="card-title">Report Credibility Analysis</div>
              </div>
              <div style={{ padding: "14px 16px", fontSize: 12 }}>

                {/* ── Overall Verdict Banner ── */}
                <div style={{
                  padding: "16px",
                  borderRadius: 10,
                  marginBottom: 16,
                  background: overallBg,
                  border: `1px solid ${overallBorder}`,
                  textAlign: "center",
                }}>
                  {/* Circular score indicator */}
                  <div style={{ position: "relative", width: 80, height: 80, margin: "0 auto 12px" }}>
                    <svg viewBox="0 0 36 36" style={{ width: 80, height: 80, transform: "rotate(-90deg)" }}>
                      <circle cx="18" cy="18" r="15.9" fill="none" stroke="var(--border)" strokeWidth="3" />
                      <circle cx="18" cy="18" r="15.9" fill="none" stroke={overallColor} strokeWidth="3"
                        strokeDasharray={`${Math.min(100, Math.max(0, overallScore))} ${100 - Math.min(100, Math.max(0, overallScore))}`}
                        strokeLinecap="round" />
                    </svg>
                    <div style={{
                      position: "absolute", top: "50%", left: "50%", transform: "translate(-50%, -50%)",
                      fontWeight: 800, fontSize: 18, color: overallColor,
                    }}>
                      {Math.round(overallScore)}%
                    </div>
                  </div>
                  <div style={{ fontWeight: 700, fontSize: 14, color: overallColor, marginBottom: 4 }}>
                    {verdictText}
                  </div>
                  {vp.pipeline_decision === "REJECTED" && vp.pipeline_rejection_reason && (
                    <div style={{
                      marginTop: 10, padding: "8px 12px", borderRadius: 6,
                      background: "var(--surface2)", border: "1px solid var(--border2)",
                      fontSize: 12, color: "var(--danger)", textAlign: "left",
                    }}>
                      <div style={{ fontWeight: 700, marginBottom: 4 }}>Why this report was not accepted:</div>
                      <div style={{ color: "var(--text)", fontWeight: 400 }}>
                        {(vp.pipeline_rejection_reason || "").replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())}
                      </div>
                    </div>
                  )}
                </div>

                {/* ── Credibility Factors ── */}
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 10 }}>
                  Credibility Factors
                </div>

                {/* Description Match */}
                {vp.incident_match && (() => {
                  const im = vp.incident_match;
                  const score = im.final_score ?? im.embedding_similarity ?? 0;
                  const label = score >= 75 ? "Strong match" : score >= 55 ? "Moderate match" : score >= 35 ? "Weak match" : "Does not match";
                  const badgeClass = score >= 75 ? "b-green" : score >= 55 ? "b-orange" : score >= 35 ? "b-orange" : "b-red";
                  return (
                    <div style={{ marginBottom: 10, padding: "12px 14px", borderRadius: 8, background: "var(--surface2)", border: "1px solid var(--border2)" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                        <div style={{ fontWeight: 700, fontSize: 12, color: "var(--text)" }}>Description Match</div>
                        <span className={`badge ${badgeClass}`} style={{ fontSize: 10 }}>
                          {label}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.5 }}>
                        How well does the description match the reported incident type
                        {im.incident_type_name ? ` (${im.incident_type_name})` : ""}?
                      </div>
                      <div style={{ marginTop: 6, fontSize: 11, color: "var(--text)", lineHeight: 1.5 }}>
                        {score >= 75 ? "The description closely matches what would be expected for this type of incident."
                          : score >= 55 ? "The description partially matches this incident type. Some details align, but more information could help."
                          : score >= 35 ? "The description has limited connection to this incident type. Consider verifying the reported category."
                          : "The description does not appear to match the selected incident type. This may need re-classification or further investigation."}
                      </div>
                    </div>
                  );
                })()}

                {/* Description Quality */}
                {vp.description_quality && (() => {
                  const dq = vp.description_quality;
                  const score = dq.description_score ?? 0;
                  const label = score >= 75 ? "Detailed & Clear" : score >= 55 ? "Adequate" : score >= 35 ? "Needs More Detail" : "Too Vague";
                  const badgeClass = score >= 75 ? "b-green" : score >= 55 ? "b-orange" : "b-red";
                  return (
                    <div style={{ marginBottom: 10, padding: "12px 14px", borderRadius: 8, background: "var(--surface2)", border: "1px solid var(--border2)" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                        <div style={{ fontWeight: 700, fontSize: 12, color: "var(--text)" }}>Description Quality</div>
                        <span className={`badge ${badgeClass}`} style={{ fontSize: 10 }}>
                          {label}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.5 }}>
                        How detailed and clear is the report description?
                      </div>
                      {dq.word_count != null && (
                        <div style={{ marginTop: 6, fontSize: 11, color: "var(--text)" }}>
                          {dq.word_count} words provided
                        </div>
                      )}
                    </div>
                  );
                })()}

                {/* Location Credibility */}
                {(() => {
                  const locComp = comps.find(c => c.name === "location_consistency");
                  if (!locComp) return null;
                  const raw = locComp.raw_score ?? 0;
                  const label = raw >= 75 ? "Confirmed in area" : raw >= 50 ? "Location verified" : raw >= 30 ? "Location uncertain" : "Location not confirmed";
                  const badgeClass = raw >= 75 ? "b-green" : raw >= 50 ? "b-orange" : "b-red";
                  return (
                    <div style={{ marginBottom: 10, padding: "12px 14px", borderRadius: 8, background: "var(--surface2)", border: "1px solid var(--border2)" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                        <div style={{ fontWeight: 700, fontSize: 12, color: "var(--text)" }}>Location Credibility</div>
                        <span className={`badge ${badgeClass}`} style={{ fontSize: 10 }}>
                          {label}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.5 }}>
                        Was the report submitted from a valid location?
                      </div>
                      <div style={{ marginTop: 6, fontSize: 11, color: "var(--text)", lineHeight: 1.5 }}>
                        {raw >= 75 ? "The reporter's location is consistent with the reported incident area."
                          : raw >= 50 ? "The reporter's location has been verified but is not in the immediate area."
                          : raw >= 30 ? "The reported location could not be fully confirmed. Consider verifying in person."
                          : "The location data does not match the reported incident area. This needs investigation."}
                      </div>
                    </div>
                  );
                })()}

                {/* Evidence Review - only show if evidence exists */}
                {(vp.evidence_match || (vp.evidence_admissibility && vp.evidence_admissibility.length > 0)) && (() => {
                  const em = vp.evidence_match;
                  const ea = vp.evidence_admissibility || [];
                  const emScore = em ? (em.final_score ?? em.semantic_similarity ?? 0) : 0;
                  const allAccepted = ea.length > 0 && ea.every(e => e.is_admissible);
                  const someRejected = ea.some(e => !e.is_admissible);

                  let label, explanation;
                  if (em && emScore >= 70) {
                    label = "Evidence supports the report";
                    explanation = "The submitted evidence is consistent with the report description.";
                  } else if (em && emScore >= 45) {
                    label = "Evidence partially supports the report";
                    explanation = "The submitted evidence somewhat aligns with the description, but the connection is not strong.";
                  } else if (em && emScore > 0) {
                    label = "Evidence does not match";
                    explanation = "The submitted evidence does not appear to support the report description. Review recommended.";
                  } else if (ea.length > 0) {
                    label = allAccepted ? "Evidence accepted" : someRejected ? "Some evidence could not be verified" : "Evidence under review";
                    explanation = `${ea.length} file${ea.length !== 1 ? "s" : ""} submitted. ${allAccepted ? "All files were accepted." : someRejected ? "Some files could not be verified as valid evidence." : ""}`;
                  } else {
                    label = "No evidence provided";
                    explanation = "No files or photos were submitted with this report.";
                  }

                  const badgeClass = (emScore >= 70 || allAccepted) ? "b-green" : (emScore >= 45 || ea.length > 0) ? "b-orange" : "b-red";

                  return (
                    <div style={{ marginBottom: 10, padding: "12px 14px", borderRadius: 8, background: "var(--surface2)", border: "1px solid var(--border2)" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                        <div style={{ fontWeight: 700, fontSize: 12, color: "var(--text)" }}>Evidence Review</div>
                        <span className={`badge ${badgeClass}`} style={{ fontSize: 10 }}>
                          {label}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: "var(--text)", lineHeight: 1.5 }}>
                        {explanation}
                      </div>
                      {ea.length > 0 && (
                        <div style={{ marginTop: 8 }}>
                          {ea.map((item, i) => (
                            <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "4px 0", borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                              <span style={{ fontSize: 11, color: "var(--muted)" }}>
                                {(item.file_type || "File").charAt(0).toUpperCase() + (item.file_type || "file").slice(1)} #{i + 1}
                              </span>
                              <span style={{
                                fontSize: 10, fontWeight: 600,
                                color: item.is_admissible ? "var(--success)" : "var(--danger)",
                              }}>
                                {item.is_admissible ? "Accepted" : "Not accepted"}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })()}

                {/* Reporter Reliability */}
                {(() => {
                  const histComp = comps.find(c => c.name === "reporter_history");
                  if (!histComp) return null;
                  const raw = histComp.raw_score ?? 0;
                  const label = raw >= 70 ? "Established reporter" : raw >= 45 ? "New reporter" : "Flagged reporter";
                  const badgeClass = raw >= 70 ? "b-green" : raw >= 45 ? "b-orange" : "b-red";
                  return (
                    <div style={{ marginBottom: 10, padding: "12px 14px", borderRadius: 8, background: "var(--surface2)", border: "1px solid var(--border2)" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                        <div style={{ fontWeight: 700, fontSize: 12, color: "var(--text)" }}>Reporter Reliability</div>
                        <span className={`badge ${badgeClass}`} style={{ fontSize: 10 }}>
                          {label}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.5 }}>
                        Based on the reporter's previous submissions
                      </div>
                      <div style={{ marginTop: 6, fontSize: 11, color: "var(--text)", lineHeight: 1.5 }}>
                        {raw >= 70 ? "This reporter has a history of submitting accurate and verified reports."
                          : raw >= 45 ? "This reporter is relatively new or has limited submission history."
                          : "This reporter has been flagged due to previously unreliable submissions. Extra verification recommended."}
                      </div>
                    </div>
                  );
                })()}

                {/* ── Trust Score Breakdown ── */}
                {comps.length > 0 && (
                  <div style={{ marginTop: 14 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 10 }}>
                      Score Breakdown
                    </div>
                    {/* Stacked horizontal bar */}
                    <div style={{ display: "flex", height: 12, borderRadius: 6, overflow: "hidden", marginBottom: 10 }}>
                      {comps.map((c, i) => {
                        const proportion = totalWeight > 0 ? ((c.weight ?? 0) / totalWeight) * 100 : 100 / comps.length;
                        const raw = c.raw_score ?? 0;
                        const cColor = raw >= 70 ? "var(--success)" : raw >= 45 ? "var(--warning)" : "var(--danger)";
                        return (
                          <div key={c.name} style={{
                            width: `${proportion}%`,
                            background: cColor,
                            opacity: 0.8,
                            borderRight: i < comps.length - 1 ? "2px solid var(--surface)" : "none",
                          }} title={friendlyNames[c.name] || (c.name || "").replace(/_/g, " ")} />
                        );
                      })}
                    </div>
                    {/* Legend */}
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {comps.map((c) => {
                        const raw = c.raw_score ?? 0;
                        const cColor = raw >= 70 ? "var(--success)" : raw >= 45 ? "var(--warning)" : "var(--danger)";
                        const friendlyLabel = raw >= 70 ? "Good" : raw >= 45 ? "Fair" : "Low";
                        return (
                          <div key={c.name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <div style={{ width: 10, height: 10, borderRadius: 3, background: cColor, flexShrink: 0 }} />
                            <span style={{ fontSize: 11, color: "var(--text)", flex: 1 }}>
                              {friendlyNames[c.name] || (c.name || "").replace(/_/g, " ")}
                            </span>
                            <span style={{ fontSize: 11, fontWeight: 600, color: cColor }}>
                              {friendlyLabel}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

              </div>
            </div>
            );
          })()}

          {/* Case Information Card */}
          {reportCase && (
            <div className="card">
              <div className="card-header">
                <div className="card-title">
                  Case Information
                  <span className={`badge ${
                    reportCase.status === 'open' ? 'b-green' : 
                    reportCase.status === 'closed' ? 'b-red' : 'b-gray'
                  }`} style={{ marginLeft: '8px', fontSize: '10px' }}>
                    {reportCase.status}
                  </span>
                </div>
                <button
                  className="btn btn-info btn-sm"
                  onClick={() => goToScreen("case-detail", reportCase.case_id)}
                  style={{ fontSize: '11px' }}
                >
                  View Full Case
                </button>
              </div>
              <div style={{ padding: "10px 14px", fontSize: 12 }}>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                    gap: 10,
                  }}
                >
                  <div>
                    <div
                      style={{
                        fontSize: 10,
                        color: "var(--muted)",
                        fontWeight: 800,
                        textTransform: "uppercase",
                        marginBottom: "4px",
                      }}
                    >
                      Case Number
                    </div>
                    <div style={{ fontWeight: "bold", color: "var(--primary)" }}>
                      {reportCase.case_number || "N/A"}
                    </div>
                  </div>
                  
                  <div>
                    <div
                      style={{
                        fontSize: 10,
                        color: "var(--muted)",
                        fontWeight: 800,
                        textTransform: "uppercase",
                        marginBottom: "4px",
                      }}
                    >
                      Case Title
                    </div>
                    <div style={{ fontWeight: "bold" }}>
                      {reportCase.title || "Untitled Case"}
                    </div>
                  </div>
                  
                  <div>
                    <div
                      style={{
                        fontSize: 10,
                        color: "var(--muted)",
                        fontWeight: 800,
                        textTransform: "uppercase",
                        marginBottom: "4px",
                      }}
                    >
                      Priority
                    </div>
                    <span className={`badge ${
                      reportCase.priority === 'urgent' ? 'b-red' : 
                      reportCase.priority === 'high' ? 'b-orange' : 
                      reportCase.priority === 'low' ? 'b-blue' : 'b-gray'
                    }`}>
                      {reportCase.priority}
                    </span>
                  </div>
                  
                  <div>
                    <div
                      style={{
                        fontSize: 10,
                        color: "var(--muted)",
                        fontWeight: 800,
                        textTransform: "uppercase",
                        marginBottom: "4px",
                      }}
                    >
                      Incident Type
                    </div>
                    <div>
                      {reportCase.incident_type?.type_name || report.incident_type_name || "Unknown"}
                    </div>
                  </div>
                  
                  <div>
                    <div
                      style={{
                        fontSize: 10,
                        color: "var(--muted)",
                        fontWeight: 800,
                        textTransform: "uppercase",
                        marginBottom: "4px",
                      }}
                    >
                      Reports in Case
                    </div>
                    <div style={{ fontWeight: "bold" }}>
                      {reportCase.report_count || 1}
                    </div>
                  </div>
                  
                  {reportCase.location && (
                    <div>
                      <div
                        style={{
                          fontSize: 10,
                          color: "var(--muted)",
                          fontWeight: 800,
                          textTransform: "uppercase",
                          marginBottom: "4px",
                        }}
                      >
                        Location
                      </div>
                      <div>
                        {reportCase.location.location_name}
                      </div>
                    </div>
                  )}
                  
                  {reportCase.assigned_to && (
                    <div>
                      <div
                        style={{
                          fontSize: 10,
                          color: "var(--muted)",
                          fontWeight: 800,
                          textTransform: "uppercase",
                          marginBottom: "4px",
                        }}
                      >
                      Assigned Officer
                      </div>
                      <div>
                        {reportCase.assigned_to.full_name || "Unknown Officer"}
                      </div>
                    </div>
                  )}
                </div>
                
                {reportCase.description && (
                  <div style={{ marginTop: "12px" }}>
                    <div
                      style={{
                        fontSize: 10,
                        color: "var(--muted)",
                        fontWeight: 800,
                        textTransform: "uppercase",
                        marginBottom: "4px",
                      }}
                    >
                      Case Description
                    </div>
                    <div style={{ fontSize: "11px", lineHeight: 1.5, fontStyle: "italic" }}>
                      {reportCase.description}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Reporter Profile Card */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">Reporter Profile</div>
            </div>
            <div style={{ padding: "10px 14px", fontSize: 12 }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: 10,
                }}
              >

                {/* Reporting Pattern */}
                <div>
                  <div
                    style={{
                      fontSize: 10,
                      color: "var(--muted)",
                      fontWeight: 800,
                      textTransform: "uppercase",
                    }}
                  >
                    Reporting Pattern
                  </div>
                  <div style={{ marginTop: 6, color: "var(--text)" }}>
                    {(() => {
                      const history = report.metadata_json?.location_history || [];
                      if (history.length < 2) {
                        return <span style={{ color: "var(--muted)", fontSize: 11 }}>Not enough reports yet to determine a pattern</span>;
                      }

                      let suspiciousJumps = 0;
                      let totalDistance = 0;

                      for (let i = 1; i < history.length; i++) {
                        const prev = history[i-1];
                        const curr = history[i];

                        if (prev.latitude && prev.longitude && curr.latitude && curr.longitude) {
                          const R = 6371;
                          const dLat = (curr.latitude - prev.latitude) * Math.PI / 180;
                          const dLon = (curr.longitude - prev.longitude) * Math.PI / 180;
                          const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                                    Math.cos(prev.latitude * Math.PI / 180) * Math.cos(curr.latitude * Math.PI / 180) *
                                    Math.sin(dLon/2) * Math.sin(dLon/2);
                          const distance = R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
                          totalDistance += distance;

                          if (distance > 50 && prev.timestamp && curr.timestamp) {
                            const timeDiff = (new Date(curr.timestamp) - new Date(prev.timestamp)) / (1000 * 60 * 60);
                            if (timeDiff < 1 && timeDiff > 0) {
                              suspiciousJumps++;
                            }
                          }
                        }
                      }

                      const avgDistance = totalDistance / (history.length - 1);
                      const consistency = suspiciousJumps === 0 ?
                        (avgDistance < 5 ? 'Consistent' : avgDistance < 20 ? 'Normal' : 'Needs Review') : 'Needs Review';

                      const explanation = consistency === 'Consistent'
                        ? 'This reporter submits from a consistent area'
                        : consistency === 'Normal'
                          ? 'This reporter submits from various areas within the district'
                          : suspiciousJumps > 0
                            ? 'Report locations have unusual gaps that may need verification'
                            : 'Reports come from widely spread locations';

                      return (
                        <>
                          <div style={{ fontSize: 11, fontWeight: 600 }}>
                            <span style={{
                              color: consistency === 'Consistent' ? 'var(--success)' :
                                     consistency === 'Normal' ? 'var(--warning)' : 'var(--danger)'
                            }}>
                              {consistency}
                            </span>
                          </div>
                          <div style={{ marginTop: 4, color: "var(--muted)", fontSize: 10 }}>
                            {explanation}
                          </div>
                        </>
                      );
                    })()}
                  </div>
                </div>

                {/* Reporting History */}
                <div>
                  <div
                    style={{
                      fontSize: 10,
                      color: "var(--muted)",
                      fontWeight: 800,
                      textTransform: "uppercase",
                    }}
                  >
                    Reporting History
                  </div>
                  <div style={{ marginTop: 6, color: "var(--text)" }}>
                    {(() => {
                      const total = Number(report.total_reports || 0);
                      const lastActiveIso =
                        report.metadata_json?.last_activity ||
                        report.metadata_json?.last_location_timestamp ||
                        report.reported_at;
                      if (total <= 1) {
                        return (
                          <div>
                            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--warning)" }}>First report</div>
                            <div style={{ marginTop: 4, color: "var(--muted)", fontSize: 10 }}>
                              This is the first report from this person
                            </div>
                          </div>
                        );
                      }
                      if (total <= 3) {
                        return (
                          <div>
                            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text)" }}>New reporter</div>
                            <div style={{ marginTop: 4, color: "var(--muted)", fontSize: 10 }}>
                              {total} reports submitted so far
                              {lastActiveIso && <> &middot; Last active {new Date(lastActiveIso).toLocaleDateString()}</>}
                            </div>
                          </div>
                        );
                      }
                      return (
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--success)" }}>Active reporter</div>
                          <div style={{ marginTop: 4, color: "var(--muted)", fontSize: 10 }}>
                            {total} reports submitted
                            {lastActiveIso && <> &middot; Last active {new Date(lastActiveIso).toLocaleDateString()}</>}
                          </div>
                        </div>
                      );
                    })()}
                  </div>
                </div>

                {/* Reporter Movement */}
                <div>
                  <div
                    style={{
                      fontSize: 10,
                      color: "var(--muted)",
                      fontWeight: 800,
                      textTransform: "uppercase",
                    }}
                  >
                    Reporter Movement
                  </div>
                  <div style={{ marginTop: 6, color: "var(--text)" }}>
                    {(() => {
                      const speed = report.movement_speed != null ? Number(report.movement_speed) : null;
                      const stationary = report.was_stationary;

                      if (speed == null && stationary == null && !report.motion_level) {
                        return <span style={{ color: "var(--muted)", fontSize: 11 }}>Movement data not available</span>;
                      }

                      let movementLabel;
                      let movementDesc;
                      let movementColor;

                      if (stationary === true || (speed != null && speed < 0.5)) {
                        movementLabel = "Stationary";
                        movementDesc = "The reporter was standing still or sitting when submitting";
                        movementColor = "var(--success)";
                      } else if (speed != null && speed < 2) {
                        movementLabel = "Walking";
                        movementDesc = "The reporter appeared to be walking when submitting";
                        movementColor = "var(--text)";
                      } else if (speed != null && speed < 8) {
                        movementLabel = "Moving quickly";
                        movementDesc = "The reporter appeared to be running or cycling when submitting";
                        movementColor = "var(--warning)";
                      } else if (speed != null) {
                        movementLabel = "In a vehicle";
                        movementDesc = "The reporter appeared to be in a moving vehicle when submitting";
                        movementColor = "var(--warning)";
                      } else {
                        movementLabel = report.motion_level || "Unknown";
                        movementDesc = "Movement was detected but exact status could not be determined";
                        movementColor = "var(--muted)";
                      }

                      return (
                        <>
                          <div style={{ fontSize: 11, fontWeight: 600, color: movementColor }}>
                            {movementLabel}
                          </div>
                          <div style={{ marginTop: 4, color: "var(--muted)", fontSize: 10 }}>
                            {movementDesc}
                          </div>
                        </>
                      );
                    })()}
                  </div>
                </div>


                              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <div className="card-title">Evidence Attachments</div>
              <span className="badge b-blue">
                {report.evidence_files?.length || 0} files
              </span>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                gap: "20px",
                padding: "10px 0",
              }}
            >
              {(report.evidence_files || []).map((ef) => (
                <div
                  key={ef.evidence_id}
                  style={{
                    background: "var(--surface2)",
                    borderRadius: "12px",
                    boxShadow: "0 4px 12px rgba(0, 0, 0, 0.12)",
                    overflow: "hidden",
                    border: "1px solid var(--border2)",
                    transition: "transform 0.3s ease, box-shadow 0.3s ease",
                    cursor: "pointer",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = "translateY(-4px)";
                    e.currentTarget.style.boxShadow =
                      "0 8px 24px rgba(0, 0, 0, 0.12)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = "translateY(0)";
                    e.currentTarget.style.boxShadow =
                      "0 4px 12px rgba(0, 0, 0, 0.08)";
                  }}
                >
                  {/* Media Container */}
                    <div style={{ position: "relative", background: "var(--background)" }}>
                    {ef.file_type === "photo" ? (
                      <>
                        <img
                          src={ef.cloudinary_url || ef.file_url}
                          alt="Evidence photo"
                          style={{
                            width: "100%",
                            height: "280px",
                            objectFit: "cover",
                            display: "block",
                          }}
                          onError={(e) => {
                            e.target.style.display = "none";
                            e.target.nextSibling.style.display = "flex";
                          }}
                        />
                        {/* Fallback */}
                        <div
                          style={{
                            display: "none",
                            height: "280px",
                            alignItems: "center",
                            justifyContent: "center",
                            flexDirection: "column",
                            background: "var(--surface2)",
                            color: "var(--muted)",
                          }}
                        >
                          <div
                            style={{ fontSize: "48px", marginBottom: "8px" }}
                          >
                            Image
                          </div>
                          <div style={{ fontSize: "14px" }}>
                            Image not available
                          </div>
                        </div>
                      </>
                    ) : ef.file_type === "audio" ? (
                      <div
                        style={{
                          height: "280px",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          flexDirection: "column",
                          background: "var(--surface2)",
                          padding: "20px",
                          boxSizing: "border-box",
                        }}
                      >
                        <div style={{ fontSize: "52px", marginBottom: "16px" }}>
                          🎵
                        </div>
                        <audio
                          controls
                          style={{
                            width: "100%",
                          }}
                        >
                          <source
                            src={ef.cloudinary_url || ef.file_url}
                            type="audio/mpeg"
                          />
                          Your browser does not support the audio tag.
                        </audio>
                      </div>
                    ) : (
                      <div style={{ position: "relative" }}>
                        <video
                          controls
                          style={{
                            width: "100%",
                            height: "280px",
                            objectFit: "cover",
                            display: "block",
                          }}
                        >
                          <source
                            src={ef.cloudinary_url || ef.file_url}
                            type="video/mp4"
                          />
                          Your browser does not support the video tag.
                        </video>
                      </div>
                    )}

                    {/* Type Badge */}
                    <div
                      style={{
                        position: "absolute",
                        top: "12px",
                        left: "12px",
                        background: "rgba(0, 0, 0, 0.7)",
                        color: "white",
                        padding: "4px 8px",
                        borderRadius: "6px",
                        fontSize: "11px",
                        fontWeight: "600",
                        backdropFilter: "blur(4px)",
                      }}
                    >
                      {ef.file_type === "photo" ? "Photo" : ef.file_type === "audio" ? "Audio" : "Video"}
                    </div>

                    {/* Quality Badge */}
                    {ef.quality_label && (
                      <div
                        style={{
                          position: "absolute",
                          top: "12px",
                          right: "12px",
                          background:
                            ef.quality_label === "good"
                              ? "var(--success)"
                              : ef.quality_label === "fair"
                                ? "var(--warning)"
                                : "var(--danger)",
                          color: "white",
                          padding: "4px 8px",
                          borderRadius: "6px",
                          fontSize: "10px",
                          fontWeight: "600",
                          textTransform: "uppercase",
                        }}
                      >
                        {ef.quality_label}
                      </div>
                    )}
                  </div>

                  {/* Content Section */}
                    <div style={{ padding: "16px" }}>
                    {/* File Info */}
                    <div style={{ marginBottom: "12px" }}>
                      <div
                        style={{
                          fontSize: "13px",
                          color: "var(--muted)",
                          marginBottom: "4px",
                        }}
                      >
                        File Size:{" "}
                        {ef.file_size
                          ? `${(ef.file_size / 1024 / 1024).toFixed(2)} MB`
                          : "Unknown"}
                      </div>
                      {ef.duration && (
                        <div
                          style={{
                            fontSize: "13px",
                            color: "var(--muted)",
                            marginBottom: "4px",
                          }}
                        >
                          Duration: {ef.duration}s
                        </div>
                      )}
                      <div style={{ fontSize: "12px", color: "var(--muted)" }}>
                        {formatLocalDateTime(ef.uploaded_at)}
                      </div>
                    </div>

                    {/* Location Info */}
                    {ef.media_latitude && ef.media_longitude && (
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "6px",
                          marginBottom: "12px",
                          fontSize: "12px",
                          color: "var(--muted)",
                        }}
                      >
                        <span>
                          {ef.media_latitude != null &&
                          ef.media_longitude != null
                            ? `${parseFloat(ef.media_latitude).toFixed(6)}, ${parseFloat(ef.media_longitude).toFixed(6)}`
                            : "Location not available"}
                        </span>
                      </div>
                    )}

                    {/* AI Analysis */}
                    {(ef.quality_label ||
                      ef.blur_score ||
                      ef.tamper_score) && (
                      <div
                        style={{
                          padding: "8px 0",
                          borderTop: "1px solid var(--border)",
                          marginTop: "8px",
                        }}
                      >
                        <div
                          style={{
                            fontSize: "11px",
                            fontWeight: "600",
                            color: "var(--text)",
                            marginBottom: "4px",
                          }}
                        >
                          AI Analysis
                        </div>
                        {typeof ef.blur_score !== "undefined" &&
                          ef.blur_score !== null && (
                            <div
                              style={{
                                fontSize: "11px",
                                color: "var(--muted)",
                                marginBottom: "2px",
                              }}
                            >
                              Blur Score: {Number(ef.blur_score).toFixed(2)}
                            </div>
                          )}
                        {typeof ef.tamper_score !== "undefined" &&
                          ef.tamper_score !== null && (
                            <div style={{ fontSize: "11px", color: "var(--muted)" }}>
                              Tamper Score: {Number(ef.tamper_score).toFixed(2)}
                            </div>
                          )}
                      </div>
                    )}

                    {/* Live Capture Badge */}
                    {ef.is_live_capture && (
                      <div
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "4px",
                          background: "var(--surface2)",
                          color: "var(--primary)",
                          padding: "4px 8px",
                          borderRadius: "4px",
                          fontSize: "11px",
                          fontWeight: "600",
                          marginTop: "8px",
                        }}
                      >
                        <span>Live Capture</span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {(!report.evidence_files ||
                report.evidence_files.length === 0) && (
                <div style={{ fontSize: "12px", color: "var(--muted)" }}>
                  No evidence uploaded.
                </div>
              )}
            </div>
          </div>

          {assignments.length > 0 && (
            <div className="card">
              <div className="card-header">
                <div className="card-title">Assignments</div>
                <span className="badge b-blue">
                  {assignments.length} active
                </span>
              </div>
              <div
                style={{
                  display: "grid",
                  gap: "8px",
                }}
              >
                {assignments.map((a) => {
                  const isMine =
                    me?.police_user_id &&
                    a.police_user_id === me.police_user_id;
                  const statusBadge =
                    a.status === "closed"
                      ? "b-green"
                      : a.status === "resolved"
                        ? "b-green"
                        : a.status === "investigating"
                          ? "b-blue"
                          : "b-orange";
                  const priorityBadge =
                    a.priority === "high"
                      ? "b-red"
                      : a.priority === "medium"
                        ? "b-orange"
                        : "b-gray";
                  return (
                    <div
                      key={a.assignment_id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "12px",
                        borderRadius: "var(--rs)",
                        border: "1px solid var(--border2)",
                        background: isMine
                          ? "rgba(79, 142, 247, 0.06)"
                          : "var(--surface2)",
                        fontSize: "12px",
                      }}
                    >
                      <div style={{ flex: 1 }}>
                        <div
                          style={{
                            fontWeight: 600,
                            marginBottom: 4,
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                          }}
                        >
                          {a.officer_name || "Officer"}
                          {isMine && (
                            <span
                              className="badge b-blue"
                              style={{ fontSize: "10px", padding: "2px 6px" }}
                            >
                              YOU
                            </span>
                          )}
                        </div>

                        {/* Station and Badge Information */}
                        <div
                          style={{
                            display: "flex",
                            gap: 12,
                            marginBottom: 4,
                            fontSize: "11px",
                            color: "var(--muted)",
                          }}
                        >
                          {a.badge_number && (
                            <span>Badge: {a.badge_number}</span>
                          )}
                          {a.station_name && (
                            <span>Station: {a.station_name}</span>
                          )}
                          {a.role && <span>Role: {a.role}</span>}
                        </div>

                        {/* Assignment Timeline */}
                        <div
                          style={{ fontSize: "11px", color: "var(--muted)" }}
                        >
                          Assigned: {formatLocalDateTime(a.assigned_at)}
                          {a.completed_at && (
                            <div style={{ marginTop: 2 }}>
                              Completed: {formatLocalDateTime(a.completed_at)}
                            </div>
                          )}
                        </div>

                        {/* Assignment Note */}
                        {a.assignment_note && (
                          <div
                            style={{
                              marginTop: 8,
                              padding: "8px",
                              background: "var(--surface2)",
                              border: "1px solid var(--border2)",
                              borderRadius: "4px",
                              fontSize: "11px",
                            }}
                          >
                            <div
                              style={{
                                fontWeight: 600,
                                marginBottom: 2,
                                color: "var(--warning)",
                              }}
                            >
                              Assignment Note:
                            </div>
                            <div style={{ color: "var(--muted)", lineHeight: 1.4 }}>
                              {a.assignment_note}
                            </div>
                          </div>
                        )}
                      </div>

                      <div
                        style={{
                          display: "flex",
                          flexDirection: "column",
                          alignItems: "flex-end",
                          gap: 6,
                        }}
                      >
                        <span
                          className={`badge ${priorityBadge}`}
                          style={{
                            fontSize: "10px",
                            textTransform: "uppercase",
                          }}
                        >
                          {a.priority} priority
                        </span>
                        <span
                          className={`badge ${statusBadge}`}
                          style={{
                            fontSize: "10px",
                            textTransform: "capitalize",
                          }}
                        >
                          {a.status}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div className="detail-col">
          <div className="card">
            <div className="card-header">
              <div className="card-title">Report Status</div>
              <span className={`badge ${operationalPipelineBadgeClass(report)}`}>
                {formatOperationalPipelineLabel(report)}
              </span>
            </div>
            <div style={{ marginBottom: "12px" }}>
              {/* Credibility Score — dynamic color */}
              {(() => {
                const ts = Math.round(trustScore || 0);
                const scoreColor = ts >= 70 ? "var(--success)" : ts >= 45 ? "var(--warning)" : "var(--danger)";
                return (
                  <>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                      <span style={{ fontSize: "11px", color: "var(--muted)" }}>Credibility Score</span>
                      <span style={{ fontFamily: '"Syne", sans-serif', fontWeight: 800, fontSize: "17px", color: scoreColor }}>
                        {ts}
                      </span>
                    </div>
                    <div className="prog-bar" style={{ marginBottom: "8px" }}>
                      <div className="prog-fill" style={{ width: `${Math.max(0, Math.min(100, ts))}%`, background: scoreColor }}></div>
                    </div>
                  </>
                );
              })()}

              <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
                {/* AI Verification */}
                <div style={{ padding: "10px", borderRadius: 8, background: "var(--surface2)", border: "1px solid var(--border2)" }}>
                  <div style={{ fontSize: "12px", fontWeight: 700, marginBottom: 6 }}>AI Verification</div>
                  <div style={{ fontSize: "11px" }}>
                    {getVerificationStatus(report)}
                  </div>
                  {isReportVerified(report) && (
                    <div style={{ fontSize: "10px", color: "var(--muted)", marginTop: 4 }}>
                      Credibility score ≥ 70% — no leader review required
                    </div>
                  )}
                  {isReportRejected(report) && (
                    <div style={{ fontSize: "10px", color: "var(--muted)", marginTop: 4 }}>
                      Credibility score too low — automatically rejected
                    </div>
                  )}
                </div>

                {/* Local Leader Review */}
                {(() => {
                  const leader = getLeaderReviewStatus(report);
                  return (
                    <div style={{ padding: "10px", borderRadius: 8, background: "var(--surface2)", border: "1px solid var(--border2)" }}>
                      <div style={{ fontSize: "12px", fontWeight: 700, marginBottom: 6 }}>Local Leader Review</div>
                      <div style={{ fontSize: "11px", color: leader.color, fontWeight: 600 }}>
                        {leader.text}
                      </div>
                      {report.leader_verified_at && (
                        <div style={{ fontSize: "10px", color: "var(--muted)", marginTop: 4 }}>
                          Reviewed on {formatLocalDateTime(report.leader_verified_at)}
                        </div>
                      )}
                      {isReportUnderReview(report) && !report.leader_verification_status && (
                        <div style={{ fontSize: "10px", color: "var(--muted)", marginTop: 4 }}>
                          Only reports with under-review status require local leader verification
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>

              {(() => {
                const cue = formatHotspotClusteringCue(report);
                return (
                  <div style={{ marginTop: 10, padding: "8px 10px", borderRadius: 8, fontSize: 11, lineHeight: 1.45, color: cue.excluded ? "var(--warning)" : "var(--muted)", background: "var(--surface2)", border: "1px solid var(--border2)" }}>
                    <div style={{ fontWeight: 700, marginBottom: 4, color: "var(--text)" }}>Area Activity</div>
                    {cue.text}
                  </div>
                );
              })()}

              <div style={{ marginTop: 12, padding: "10px", borderRadius: 8, background: "var(--surface2)", border: "1px solid var(--border2)" }}>
                <div style={{ fontSize: "12px", fontWeight: 700, marginBottom: 6 }}>Community Feedback</div>
                {totalVotes > 0 ? (
                  <>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 6, fontSize: 11 }}>
                      <div><strong>{realVotes}</strong> Confirmed real</div>
                      <div><strong>{unknownVotes}</strong> Unsure</div>
                      <div><strong>{falseVotes}</strong> Reported false</div>
                    </div>
                    <div style={{ marginTop: 8, height: 6, width: "100%", borderRadius: 999, overflow: "hidden", display: "flex", background: "var(--border2)" }}>
                      <div style={{ width: `${(realVotes / totalVotes) * 100}%`, background: "var(--success)" }} />
                      <div style={{ width: `${(unknownVotes / totalVotes) * 100}%`, background: "var(--muted)" }} />
                      <div style={{ width: `${(falseVotes / totalVotes) * 100}%`, background: "var(--danger)" }} />
                    </div>
                    <div style={{ marginTop: 6, fontSize: 10, color: "var(--muted)" }}>
                      {totalVotes} community member{totalVotes !== 1 ? 's' : ''} voted
                    </div>
                  </>
                ) : (
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>No community feedback received yet.</div>
                )}
              </div>

              {report.flag_reason && (
                <div style={{ marginTop: 10, padding: "10px", borderRadius: 8, background: "var(--surface2)", border: "1px solid var(--border2)" }}>
                  <div style={{ fontSize: "11px", fontWeight: 700, marginBottom: 4 }}>Review Notes</div>
                  <div style={{ fontSize: "11px", color: "var(--text)" }}>{friendlyFlagReason(report.flag_reason)}</div>
                </div>
              )}
            </div>
          </div>

          {/* Related reports card */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">Related Reports</div>
            </div>
            <div style={{ padding: "10px 14px", fontSize: "12px" }}>
              {relatedLoading && (
                <div style={{ fontSize: "12px", color: "var(--muted)" }}>
                  Loading related reports…
                </div>
              )}
              {!relatedLoading && relatedReports.length === 0 && (
                <div style={{ fontSize: "12px", color: "var(--muted)" }}>
                  No similar reports found in the last few days.
                </div>
              )}
              {relatedReports.map((r) => (
                <div
                  key={r.report_id}
                  style={{
                    padding: "8px 0",
                    borderBottom: "1px solid var(--border2)",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      marginBottom: 2,
                    }}
                  >
                    <span
                      style={{
                        fontSize: "11px",
                        fontFamily: "monospace",
                        color: "var(--muted)",
                      }}
                    >
                      {r.report_number || String(r.report_id).slice(0, 8)}
                    </span>
                    <span
                      className={`badge ${
                        r.rule_status === "passed"
                          ? "b-green"
                          : r.rule_status === "pending"
                            ? "b-orange"
                            : "b-red"
                      }`}
                      style={{ fontSize: "10px" }}
                    >
                      {r.rule_status}
                    </span>
                  </div>
                  <div style={{ fontSize: "11px" }}>
                    {r.incident_type_name || "—"} · {r.village_name || "—"}
                  </div>
                  <div
                    style={{
                      fontSize: "10px",
                      color: "var(--muted)",
                      marginTop: 2,
                    }}
                  >
                    {formatLocalDateTime(r.reported_at)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Case Linking Modal */}
      {showLinkCaseModal && (
        <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && setShowLinkCaseModal(false)}>
          <div className="modal" style={{ maxWidth: '600px', width: '90%' }}>
            <div className="modal-header">
              <div className="modal-title">
                {report.case_id ? "Move Report to Different Case" : "Link Report to Existing Case"}
              </div>
              <div className="modal-close" onClick={() => setShowLinkCaseModal(false)}>✕</div>
            </div>

            <div style={{ 
              padding: '12px', 
              backgroundColor: 'var(--surface2)',
              border: '1px solid var(--border2)', 
              borderRadius: '6px', 
              marginBottom: '16px',
              fontSize: '12px',
              color: 'var(--text)'
            }}>
              <strong>Filtering Rules:</strong>
              <ul style={{ margin: '4px 0 0 0', paddingLeft: '16px' }}>
                <li>Only showing cases with incident type: <strong>{report.incident_type_name || 'Unknown'}</strong></li>
                {report.case_id && <li>Current case is excluded from the list</li>}
                <li>Reports can only be linked to cases with matching incident types</li>
              </ul>
            </div>

            <div className="input-group">
              <div className="input-label">Search Cases</div>
              <input
                type="text"
                placeholder="Search by case number, title, or location..."
                value={caseSearch}
                onChange={(e) => {
                  setCaseSearch(e.target.value);
                  loadAvailableCases();
                }}
                style={{ 
                  width: '100%', 
                  padding: '8px', 
                  border: '1px solid var(--border)', 
                  borderRadius: '4px',
                  marginBottom: '12px'
                }}
              />
            </div>

            <div className="input-group">
              <div className="input-label">Select Case</div>
              {casesLoading ? (
                <div style={{ padding: '20px', textAlign: 'center', color: 'var(--muted)' }}>
                  Loading cases...
                </div>
              ) : availableCases.length === 0 ? (
                <div style={{ padding: '20px', textAlign: 'center', color: 'var(--muted)' }}>
                  No cases found. Try adjusting your search.
                </div>
              ) : (
                <div style={{ 
                  maxHeight: '300px', 
                  overflowY: 'auto', 
                  border: '1px solid var(--border)', 
                  borderRadius: '4px'
                }}>
                  {availableCases.map((case_item) => (
                    <div
                      key={case_item.case_id}
                      onClick={() => setSelectedCase(case_item.case_id)}
                      style={{
                        padding: '12px',
                        borderBottom: '1px solid var(--border)',
                        cursor: 'pointer',
                        backgroundColor: selectedCase === case_item.case_id ? 'var(--primary)' : 'transparent',
                        color: selectedCase === case_item.case_id ? 'white' : 'var(--text)',
                      }}
                    >
                      <div style={{ fontWeight: 'bold', marginBottom: '4px' }}>
                        {case_item.case_number || case_item.title || 'Unknown Case'}
                      </div>
                      <div style={{ fontSize: '12px', opacity: 0.8, marginBottom: '2px' }}>
                        {case_item.title || 'No title'}
                      </div>
                      <div style={{ fontSize: '11px', opacity: 0.7 }}>
                        Status: <span className={`badge ${case_item.status === 'open' ? 'b-green' : 'b-gray'}`}>
                          {case_item.status}
                        </span>
                        {' • '}
                        Priority: <span className={`badge ${
                          case_item.priority === 'urgent' ? 'b-red' : 
                          case_item.priority === 'high' ? 'b-orange' : 
                          case_item.priority === 'low' ? 'b-blue' : 'b-gray'
                        }`}>
                          {case_item.priority}
                        </span>
                        {' • '}
                        {case_item.report_count || 0} reports
                      </div>
                      {case_item.location?.location_name && (
                        <div style={{ fontSize: '11px', opacity: 0.7, marginTop: '2px' }}>
                          {case_item.location.location_name}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
            
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', marginTop: '16px' }}>
              <button 
                className="btn btn-outline" 
                onClick={() => setShowLinkCaseModal(false)} 
                disabled={linkingCase}
              >
                Cancel
              </button>
              <button 
                className="btn btn-primary" 
                onClick={linkReportToCase} 
                disabled={!selectedCase || linkingCase}
              >
                {linkingCase 
                  ? (report.case_id ? "Moving..." : "Linking...") 
                  : (report.case_id ? "Move Report" : "Link Report")
                }
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default ReportDetail;
