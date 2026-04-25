import React, { useEffect, useState } from "react";
import api from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { formatLocalDateTime } from "../../utils/dateTime";

const friendlyFlagReason = (reason) => {
  const m = {
    evidence_time_mismatch:
      "Evidence was captured too long before the report was submitted.",
    stale_live_capture_timestamp:
      "Live-capture evidence timestamp appears stale.",
    incident_description_mismatch:
      "Description appears inconsistent with the selected incident type.",
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
const isReportVerified = (report, mlPrediction) => {
  const status = (report.rule_status || "").toLowerCase();
  const hasOfficerConfirmed = report.reviews?.some(
    (rv) => (rv.decision || "").toLowerCase() === "confirmed",
  );

  if (hasOfficerConfirmed) {
    return true; // Officer-verified
  }

  if (status === "passed") {
    // Check ML confidence
    if (
      mlPrediction &&
      mlPrediction.trust_score !== null &&
      mlPrediction.trust_score !== undefined
    ) {
      const mlConfidence = parseFloat(mlPrediction.trust_score) || 0;
      return mlConfidence >= 70; // Auto-verified if ML confidence >= 70 (optimized threshold)
    }
  }

  return false; // Not verified
};

const getVerificationStatus = (report, mlPrediction) => {
  const status = (report.rule_status || "").toLowerCase();
  const hasOfficerConfirmed = report.reviews?.some(
    (rv) => (rv.decision || "").toLowerCase() === "confirmed",
  );

  if (hasOfficerConfirmed) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: "11px",
        }}
      >
        <span style={{ color: "#4caf50", fontWeight: 600 }}>
          Officer verified
        </span>
        <span style={{ color: "#666" }}>
          — Confirmed by{" "}
          {report.reviews.find(
            (rv) => (rv.decision || "").toLowerCase() === "confirmed",
          )?.reviewer_name || "officer"}
        </span>
      </div>
    );
  }

  if (status === "passed") {
    if (
      mlPrediction &&
      mlPrediction.trust_score !== null &&
      mlPrediction.trust_score !== undefined
    ) {
      const mlConfidence = parseFloat(mlPrediction.trust_score) || 0;

      if (mlConfidence >= 70) {
        return (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontSize: "11px",
            }}
          >
            <span style={{ color: "#4caf50", fontWeight: 600 }}>
              AI-verified
            </span>
            <span style={{ color: "#666" }}>
              — ML confidence: {mlConfidence.toFixed(1)}%
            </span>
          </div>
        );
      } else {
        return (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontSize: "11px",
            }}
          >
            <span style={{ color: "#ff9800", fontWeight: 600 }}>
              Low ML Confidence
            </span>
            <span style={{ color: "#666" }}>
              - Current: {mlConfidence.toFixed(1)}% (needs ≥70%)
            </span>
          </div>
        );
      }
    } else if (
      report.ml_predictions && 
      report.ml_predictions.length > 0 &&
      !mlPrediction?.prediction_label
    ) {
      // Text analysis case
      const latestPrediction = report.ml_predictions.reduce((latest, pred) => {
        return (!latest || new Date(pred.evaluated_at) > new Date(latest.evaluated_at)) ? pred : latest;
      }, null);
      const textConfidence = latestPrediction ? parseFloat(latestPrediction.trust_score) : 0;
      
      return (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: "11px",
          }}
        >
          <span 
            style={{ 
              color: textConfidence >= 70 ? "#4caf50" : textConfidence >= 40 ? "#ff9800" : "#f44336", 
              fontWeight: 600 
            }}
          >
            Text Analysis
          </span>
          <span style={{ color: "#666" }}>
            — Confidence: {textConfidence.toFixed(1)}%
          </span>
        </div>
      );
    } else {
      return (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: "11px",
          }}
        >
          <span style={{ color: "#ff9800", fontWeight: 600 }}>
            No ML Analysis
          </span>
          <span style={{ color: "#666" }}>- Requires officer verification</span>
        </div>
      );
    }
  }

  if (status === "pending") {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: "11px",
        }}
      >
        <span style={{ color: "#ff9800", fontWeight: 600 }}>
          Pending Review
        </span>
        <span style={{ color: "#666" }}>
          - Needs officer assignment and confirmation
        </span>
      </div>
    );
  }

  if (status === "flagged" || status === "rejected") {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: "11px",
        }}
      >
        <span style={{ color: "#f44336", fontWeight: 600 }}>
          {status === "flagged" ? "Flagged" : "Rejected"}
        </span>
        <span style={{ color: "#666" }}>- Cannot contribute to hotspots</span>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        fontSize: "11px",
      }}
    >
      <span style={{ color: "#9e9e9e", fontWeight: 600 }}>Unknown Status</span>
      <span style={{ color: "#666" }}>- Status unclear</span>
    </div>
  );
};

const getVerificationRequirements = (report, mlPrediction) => {
  const status = (report.rule_status || "").toLowerCase();
  const hasOfficerConfirmed = report.reviews?.some(
    (rv) => (rv.decision || "").toLowerCase() === "confirmed",
  );

  if (hasOfficerConfirmed) {
    return null; // Already verified
  }

  if (status === "passed") {
    if (
      mlPrediction &&
      mlPrediction.trust_score !== null &&
      mlPrediction.trust_score !== undefined
    ) {
      const mlConfidence = parseFloat(mlPrediction.trust_score) || 0;

      if (mlConfidence < 70) {
        return (
          <div>
            <div style={{ marginBottom: "4px" }}>
              ML confidence too low ({mlConfidence.toFixed(1)}% &lt; 70%)
            </div>
            <div style={{ marginBottom: "4px" }}>
              <strong>Option 1:</strong> Assign to officer for confirmation
            </div>
            <div style={{ marginBottom: "4px" }}>
              <strong>Option 2:</strong> Wait for more reports from this device
            </div>
            <div>
              <strong>Option 3:</strong> Flag if suspicious patterns detected
            </div>
          </div>
        );
      } else {
        return null; // ML confidence is sufficient for AI verification
      }
    } else if (
      report.ml_predictions && 
      report.ml_predictions.length > 0 &&
      !mlPrediction?.prediction_label
    ) {
      // Text analysis case
      const latestPrediction = report.ml_predictions.reduce((latest, pred) => {
        return (!latest || new Date(pred.evaluated_at) > new Date(latest.evaluated_at)) ? pred : latest;
      }, null);
      const textConfidence = latestPrediction ? parseFloat(latestPrediction.trust_score) : 0;
      
      return (
        <div>
          <div style={{ marginBottom: "4px" }}>
            Text analysis available ({textConfidence.toFixed(1)}% confidence)
          </div>
          {textConfidence < 70 && (
            <div>
              <strong>Recommended:</strong> Assign to officer for manual verification due to low confidence
            </div>
          )}
        </div>
      );
    } else {
      return (
        <div>
          <div style={{ marginBottom: "4px" }}>No ML analysis available</div>
          <div>
            <strong>Required:</strong> Assign to officer for manual verification
          </div>
        </div>
      );
    }
  }

  if (status === "pending") {
    return (
      <div>
        <div style={{ marginBottom: "4px" }}>
          Report status is "pending" (needs officer review)
        </div>
        <div>
          <strong>Required:</strong> Assign to officer and get confirmation
        </div>
      </div>
    );
  }

  if (status === "flagged" || status === "rejected") {
    return (
      <div>
        <div style={{ marginBottom: "4px" }}>
          Report is {status} (cannot be verified)
        </div>
        <div>
          <strong>Result:</strong> This report cannot contribute to hotspots
        </div>
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: "4px" }}>Verification status unclear</div>
      <div>
        <strong>Required:</strong> Assign to officer for review
      </div>
    </div>
  );
};

const ReportDetail = ({ goToScreen, openModal, reportId, wsRefreshKey }) => {
  const { user: me } = useAuth();
  const role = me?.role || "officer";

  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [savingDecision, setSavingDecision] = useState("");
  const [showReasonModal, setShowReasonModal] = useState(false);
  const [pendingDecision, setPendingDecision] = useState("");
  const [reviewReason, setReviewReason] = useState("");
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

  const submitReview = async (decision) => {
    if (!reportId) return;
    
    // Show reason modal first
    setPendingDecision(decision);
    setReviewReason("");
    setShowReasonModal(true);
  };

  const confirmReview = async () => {
    if (!reportId || !pendingDecision) return;
    setSavingDecision(pendingDecision);
    setError("");
    setActionMessage("");
    try {
      const reviewRes = await api.post(`/api/v1/reports/${reportId}/reviews`, {
        decision: pendingDecision,
        review_note: reviewReason,
      });
      const review =
        reviewRes && typeof reviewRes === "object"
          ? reviewRes
          : {
              review_id: `${reportId}-${pendingDecision}-${Date.now()}`,
              report_id: reportId,
              police_user_id: me?.police_user_id,
              decision: pendingDecision,
              review_note: reviewReason,
              created_at: new Date().toISOString(),
            };

      setReport((prev) => ({
        ...prev,
        reviews: [...(prev.reviews || []), review],
        verification_status:
          pendingDecision === "confirmed" ? "verified" : "flagged",
      }));

      setActionMessage(
        pendingDecision === "confirmed"
          ? "✅ Report verified successfully"
          : "🚩 Report flagged for review"
      );

      // Close modal and reset
      setShowReasonModal(false);
      setPendingDecision("");
      setReviewReason("");

      // Keep server truth in sync without changing the current screen.
      refreshInBackground();
    } catch (e) {
      setError(e?.message || "Failed to submit review.");
    } finally {
      setSavingDecision("");
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
      
      const response = await api.get(`/api/v1/cases?${params}`);
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
        setActionMessage("✅ Report moved to different case successfully");
      } else {
        await api.post(`/api/v1/cases/${selectedCase}/reports`, {
          report_ids: [reportId]
        });
        setActionMessage("✅ Report linked to case successfully");
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
        errorMessage = "❌ Cannot link to this case: Incident types don't match. Reports can only be linked to cases with the same incident type.";
      } else if (errorMessage.includes("already linked to another case")) {
        errorMessage = "❌ This report is already linked to a case. Use the 'Move to different case' option instead.";
      } else if (errorMessage.includes("Access denied")) {
        errorMessage = "❌ You don't have permission to link to this case.";
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

      setActionMessage("✅ Report unlinked from case successfully");
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
  const trustScore = report.trust_score ?? 0;
  const trustFactors = report.trust_factors || {};
  const createdAt = formatLocalDateTime(report.reported_at);
  const assignments = report.assignments || [];
  const hasCase = report.case_id; // Assuming case_id is available
  const locationHierarchy = [
    report.incident_sector_name,
    report.incident_cell_name,
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
          Report {idLabel}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            className={`badge ${statusConfig.color}`}
            style={{ fontSize: "12px", padding: "4px 8px" }}
          >
            {statusConfig.text}
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
          {/* Review Status Buttons: available to all roles */}
          <button
            className="btn btn-success btn-sm"
            onClick={() => submitReview("confirmed")}
            disabled={!!savingDecision}
            style={{ display: "flex", alignItems: "center", gap: 4 }}
          >
            {savingDecision === "confirmed"
              ? "Verifying…"
              : "Verify report"}
          </button>
          <button
            className="btn btn-danger btn-sm"
            onClick={() => submitReview("rejected")}
            disabled={!!savingDecision}
            style={{ display: "flex", alignItems: "center", gap: 4 }}
          >
            {savingDecision === "rejected" ? "Flagging…" : "Flag report"}
          </button>
          
          {/* Assignment and Case Management: admin/supervisor only */}
          {(role === "admin" || role === "supervisor") && (
            <>
              <button
                className="btn btn-primary btn-sm"
                onClick={() => openModal("assign")}
                style={{ display: "flex", alignItems: "center", gap: 4 }}
              >
                Assign officer
              </button>

              {!hasCase ? (
                <button
                  className="btn btn-success btn-sm"
                  onClick={() => openModal("newCase")}
                  style={{ display: "flex", alignItems: "center", gap: 4 }}
                >
                  Create case
                </button>
              ) : (
                <>
                  <button
                    className="btn btn-info btn-sm"
                    onClick={() => goToScreen("case-detail", report.case_id)}
                    style={{ display: "flex", alignItems: "center", gap: 4 }}
                  >
                    View case
                  </button>
                  
                  <button
                    className="btn btn-danger btn-sm"
                    onClick={unlinkReportFromCase}
                    disabled={linkingCase}
                    style={{ display: "flex", alignItems: "center", gap: 4 }}
                  >
                    {linkingCase ? "Unlinking..." : "Unlink from case"}
                  </button>
                </>
              )}

              <button
                className="btn btn-warn btn-sm"
                onClick={openLinkCaseModal}
                disabled={linkingCase}
                style={{ display: "flex", alignItems: "center", gap: 4 }}
              >
                {linkingCase 
                  ? "Processing..." 
                  : (report.case_id ? "Move to different case" : "Link to existing case")
                }
              </button>
            </>
          )}
        </div>
      </div>

      {actionMessage && (
        <div
          style={{
            marginBottom: 12,
            padding: "10px 12px",
            borderRadius: 8,
            background: "rgba(76, 175, 80, 0.12)",
            border: "1px solid rgba(76, 175, 80, 0.35)",
            color: "var(--text)",
            fontSize: 12,
          }}
        >
          {actionMessage}
        </div>
      )}

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
                  background: "rgba(255, 152, 0, 0.12)",
                  border: "1px solid rgba(255, 152, 0, 0.35)",
                  color: "var(--text)",
                  fontSize: 12,
                }}
              >
                <strong>Review reason:</strong>{" "}
                {friendlyFlagReason(report.flag_reason)}
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
                <div className="dfl">GPS Coords</div>
                <div
                  className="dfv"
                  style={{ fontSize: "11px", fontFamily: "monospace" }}
                >
                  {coordsText}
                </div>
              </div>
              <div className="detail-field">
                <div className="dfl">Navigation</div>
                <div className="dfv">
                  {report.latitude && report.longitude ? (
                    <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                      <button
                        onClick={() => {
                          const lat = parseFloat(report.latitude);
                          const lon = parseFloat(report.longitude);
                          window.open(
                            `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`,
                            '_blank'
                          );
                        }}
                        style={{
                          padding: "6px 12px",
                          fontSize: "11px",
                          backgroundColor: "var(--primary)",
                          color: "white",
                          border: "none",
                          borderRadius: "4px",
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          gap: "4px"
                        }}
                      >
                        🚗 Navigate to report
                      </button>
                      <button
                        onClick={() => {
                          const lat = parseFloat(report.latitude);
                          const lon = parseFloat(report.longitude);
                          window.open(
                            `https://www.google.com/maps?q=${lat},${lon}`,
                            '_blank'
                          );
                        }}
                        style={{
                          padding: "6px 12px",
                          fontSize: "11px",
                          backgroundColor: "var(--secondary)",
                          color: "white",
                          border: "none",
                          borderRadius: "4px",
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          gap: "4px"
                        }}
                      >
                        📍 Open map
                      </button>
                    </div>
                  ) : (
                    <span style={{ color: "var(--muted)", fontSize: "12px" }}>
                      Location not available
                    </span>
                  )}
                </div>
              </div>
              <div className="detail-field">
                <div className="dfl">GPS Accuracy</div>
                <div className="dfv" style={{ fontSize: "12px" }}>
                  {report.gps_accuracy != null
                    ? `${Number(report.gps_accuracy).toFixed(1)}m`
                    : "—"}
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

          {/* Case Information Card */}
          {reportCase && (
            <div className="card">
              <div className="card-header">
                <div className="card-title">
                  📋 Case Information
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
                        📍 {reportCase.location.location_name}
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
                        👮 {reportCase.assigned_to.full_name || "Unknown Officer"}
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

          {/* Enhanced Reporter Context Card */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">Reporter Context</div>
            </div>
            <div style={{ padding: "10px 14px", fontSize: 12 }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: 10,
                }}
              >
                
                {/* Location Consistency */}
                <div>
                  <div
                    style={{
                      fontSize: 10,
                      color: "var(--muted)",
                      fontWeight: 800,
                      textTransform: "uppercase",
                    }}
                  >
                    Location Consistency
                  </div>
                  <div style={{ marginTop: 6, color: "var(--text)" }}>
                    {(() => {
                      const history = report.metadata_json?.location_history || [];
                      if (history.length < 2) {
                        return <span style={{ color: "var(--muted)", fontSize: 11 }}>Insufficient data</span>;
                      }
                      
                      // Check for suspicious jumps (simplified analysis)
                      let suspiciousJumps = 0;
                      let totalDistance = 0;
                      
                      for (let i = 1; i < history.length; i++) {
                        const prev = history[i-1];
                        const curr = history[i];
                        
                        if (prev.latitude && prev.longitude && curr.latitude && curr.longitude) {
                          // Calculate distance between consecutive points
                          const R = 6371; // Earth's radius in km
                          const dLat = (curr.latitude - prev.latitude) * Math.PI / 180;
                          const dLon = (curr.longitude - prev.longitude) * Math.PI / 180;
                          const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                                    Math.cos(prev.latitude * Math.PI / 180) * Math.cos(curr.latitude * Math.PI / 180) *
                                    Math.sin(dLon/2) * Math.sin(dLon/2);
                          const distance = R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
                          totalDistance += distance;
                          
                          // Check for suspicious jumps (>50km in <1 hour)
                          if (distance > 50 && prev.timestamp && curr.timestamp) {
                            const timeDiff = (new Date(curr.timestamp) - new Date(prev.timestamp)) / (1000 * 60 * 60); // hours
                            if (timeDiff < 1 && timeDiff > 0) {
                              suspiciousJumps++;
                            }
                          }
                        }
                      }
                      
                      const avgDistance = totalDistance / (history.length - 1);
                      const consistency = suspiciousJumps === 0 ? 
                        (avgDistance < 5 ? 'High' : avgDistance < 20 ? 'Medium' : 'Low') : 'Suspicious';
                      
                      return (
                        <>
                          <div style={{ fontSize: 11, fontWeight: 600 }}>
                            <span style={{
                              color: consistency === 'High' ? 'var(--success)' :
                                     consistency === 'Medium' ? 'var(--warning)' :
                                     consistency === 'Low' ? 'var(--orange)' : 'var(--danger)'
                            }}>
                              {consistency}
                            </span>
                          </div>
                          <div style={{ marginTop: 4, color: "var(--muted)", fontSize: 10 }}>
                            Avg movement: {avgDistance.toFixed(1)}km between reports
                            {suspiciousJumps > 0 && (
                              <div style={{ color: "var(--danger)", marginTop: 2 }}>
                                ⚠️ {suspiciousJumps} suspicious jump{suspiciousJumps > 1 ? 's' : ''}
                              </div>
                            )}
                          </div>
                        </>
                      );
                    })()}
                  </div>
                </div>

                {/* Device Activity Pattern */}
                <div>
                  <div
                    style={{
                      fontSize: 10,
                      color: "var(--muted)",
                      fontWeight: 800,
                      textTransform: "uppercase",
                    }}
                  >
                    Activity Pattern
                  </div>
                  <div style={{ marginTop: 6, color: "var(--text)" }}>
                    {(() => {
                      const total = Number(report.total_reports || 0);
                      const lastActiveIso =
                        report.metadata_json?.last_activity ||
                        report.metadata_json?.last_location_timestamp ||
                        report.reported_at;
                      const rel = relativeTime(lastActiveIso);
                      if (total <= 1) {
                        return (
                          <span style={{ color: "var(--muted)", fontSize: 11 }}>
                            Limited history (first report)
                          </span>
                        );
                      }
                      if (!rel) {
                        return (
                          <span style={{ color: "var(--muted)", fontSize: 11 }}>
                            Activity history unavailable
                          </span>
                        );
                      }
                      return (
                        <>
                          <div style={{ fontSize: 11 }}>
                            Last active:{" "}
                            {lastActiveIso
                              ? new Date(lastActiveIso).toLocaleDateString()
                              : "—"}
                          </div>
                          <div
                            style={{
                              marginTop: 4,
                              color: "var(--muted)",
                              fontSize: 10,
                            }}
                          >
                            {rel}
                          </div>
                        </>
                      );
                    })()}
                  </div>
                </div>

                {/* Device Trust Score */}
                <div>
                  <div
                    style={{
                      fontSize: 10,
                      color: "var(--muted)",
                      fontWeight: 800,
                      textTransform: "uppercase",
                    }}
                  >
                    Device Trust Score
                  </div>
                  <div style={{ marginTop: 6 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <div style={{ width: 60, height: 8, background: "var(--border)", borderRadius: 4, overflow: "hidden" }}>
                        <div style={{
                          width: `${Math.min(100, Math.max(0, report.device_trust_score || 0))}%`,
                          height: "100%",
                          background: (report.device_trust_score || 0) >= 70 ? "var(--success)" : (report.device_trust_score || 0) >= 40 ? "var(--warning)" : "var(--danger)",
                          transition: "width 0.3s ease",
                        }} />
                      </div>
                      <span style={{
                        fontSize: 11,
                        fontWeight: 600,
                        color: (report.device_trust_score || 0) >= 70 ? "var(--success)" : (report.device_trust_score || 0) >= 40 ? "var(--warning)" : "var(--danger)",
                      }}>
                        {Math.round(report.device_trust_score || 0)}
                      </span>
                    </div>
                    <div style={{ marginTop: 4, color: "var(--muted)", fontSize: 10 }}>
                      {report.total_reports || 0} total reports · {(report.trusted_reports || 0)} trusted
                    </div>
                  </div>
                </div>

                {/* Context tags */}
                <div>
                  <div
                    style={{
                      fontSize: 10,
                      color: "var(--muted)",
                      fontWeight: 800,
                      textTransform: "uppercase",
                    }}
                  >
                    Context tags
                  </div>
                  <div
                    style={{
                      marginTop: 6,
                      display: "flex",
                      gap: 6,
                      flexWrap: "wrap",
                    }}
                  >
                    {(report.context_tags || []).length ? (
                      (report.context_tags || []).map((t) => (
                        <span
                          key={t}
                          className="badge b-gray"
                          style={{ fontSize: 10 }}
                        >
                          {t}
                        </span>
                      ))
                    ) : (
                      <span style={{ color: "var(--muted)" }}>—</span>
                    )}
                  </div>
                </div>

                {/* Motion */}
                <div>
                  <div
                    style={{
                      fontSize: 10,
                      color: "var(--muted)",
                      fontWeight: 800,
                      textTransform: "uppercase",
                    }}
                  >
                    Motion
                  </div>
                  <div style={{ marginTop: 6, color: "var(--text)" }}>
                    Level: {report.motion_level || "—"}
                    <div style={{ marginTop: 4, color: "var(--muted)" }}>
                      Speed:{" "}
                      {report.movement_speed != null
                        ? `${Number(report.movement_speed).toFixed(2)} m/s`
                        : "—"}
                      {" · "}
                      Stationary:{" "}
                      {report.was_stationary == null
                        ? "—"
                        : report.was_stationary
                          ? "Yes"
                          : "No"}
                    </div>
                  </div>
                </div>

                {/* Location History */}
                <div style={{ gridColumn: "1 / -1", marginTop: "10px" }}>
                  <div
                    style={{
                      fontSize: 10,
                      color: "var(--muted)",
                      fontWeight: 800,
                      textTransform: "uppercase",
                      marginBottom: "6px",
                    }}
                  >
                    📍 Location History
                  </div>
                  {locationLoading ? (
                    <div style={{ padding: "10px", textAlign: "center", color: "var(--muted)" }}>
                      Loading location history...
                    </div>
                  ) : locationHistory ? (
                    <div>
                      <div style={{ 
                        fontSize: "11px", 
                        marginBottom: "8px",
                        padding: "8px",
                        backgroundColor: "var(--surface2)",
                        borderRadius: "6px",
                        border: "1px solid var(--border)"
                      }}>
                        <strong>Current Location:</strong> {locationHistory.current_location?.sector || 'Unknown'} {'>'} {locationHistory.current_location?.cell || 'Unknown'} {'>'} {locationHistory.current_location?.village || 'Unknown'}
                        <div style={{ marginTop: "4px", color: "var(--muted)" }}>
                          Total Reports: {locationHistory.total_reports} • Location Changes: {locationHistory.location_changes}
                        </div>
                      </div>
                      
                      {locationHistory.history.length > 1 && (
                        <div style={{ 
                          maxHeight: "200px", 
                          overflowY: "auto",
                          border: "1px solid var(--border)",
                          borderRadius: "6px",
                          backgroundColor: "var(--surface)"
                        }}>
                          {locationHistory.history.slice(0, 10).map((entry, index) => (
                            <div
                              key={entry.report_id}
                              style={{
                                padding: "8px 10px",
                                borderBottom: index < locationHistory.history.slice(0, 10).length - 1 ? "1px solid var(--border)" : "none",
                                fontSize: "10px",
                                backgroundColor: entry.location_changed ? "rgba(255, 152, 0, 0.1)" : "transparent",
                                borderLeft: entry.location_changed ? "3px solid var(--warning)" : "3px solid transparent"
                              }}
                            >
                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                <div>
                                  <span style={{ fontWeight: "bold", color: "var(--primary)" }}>
                                    {entry.report_number || entry.report_id.slice(0, 8)}
                                  </span>
                                  {entry.location_changed && (
                                    <span style={{ 
                                      marginLeft: "6px", 
                                      padding: "2px 6px", 
                                      backgroundColor: "var(--warning)", 
                                      color: "white", 
                                      borderRadius: "3px", 
                                      fontSize: "9px",
                                      fontWeight: "bold"
                                    }}>
                                      📍 MOVED
                                    </span>
                                  )}
                                </div>
                                <div style={{ color: "var(--muted)" }}>
                                  {new Date(entry.timestamp).toLocaleString()}
                                </div>
                              </div>
                              <div style={{ marginTop: "4px", color: "var(--text)" }}>
                                {entry.sector || 'Unknown'} {'>'} {entry.cell || 'Unknown'} {'>'} {entry.village || 'Unknown'}
                              </div>
                              {entry.latitude && entry.longitude && (
                                <div style={{ marginTop: "2px", color: "var(--muted)", fontSize: "9px" }}>
                                  📍 {entry.latitude.toFixed(6)}, {entry.longitude.toFixed(6)}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                      
                      {locationHistory.history.length > 10 && (
                        <div style={{ 
                          marginTop: "6px", 
                          textAlign: "center", 
                          fontSize: "10px", 
                          color: "var(--muted)" 
                        }}>
                          Showing 10 of {locationHistory.history.length} location entries
                        </div>
                      )}
                    </div>
                  ) : (
                    <div style={{ 
                      padding: "10px", 
                      textAlign: "center", 
                      color: "var(--muted)",
                      fontSize: "11px",
                      backgroundColor: "var(--surface2)",
                      borderRadius: "6px",
                      border: "1px solid var(--border)"
                    }}>
                      No location history available
                    </div>
                  )}
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
                            background: "#f8f9fa",
                            color: "#666",
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
                      {ef.file_type === "photo" ? "Photo" : "Video"}
                    </div>

                    {/* Quality Badge */}
                    {ef.ai_quality_label && (
                      <div
                        style={{
                          position: "absolute",
                          top: "12px",
                          right: "12px",
                          background:
                            ef.ai_quality_label === "good"
                              ? "#28a745"
                              : ef.ai_quality_label === "fair"
                                ? "#fd7e14"
                                : "#dc3545",
                          color: "white",
                          padding: "4px 8px",
                          borderRadius: "6px",
                          fontSize: "10px",
                          fontWeight: "600",
                          textTransform: "uppercase",
                        }}
                      >
                        {ef.ai_quality_label}
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
                          color: "#666",
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
                    {(ef.ai_quality_label ||
                      ef.blur_score ||
                      ef.tamper_score) && (
                      <div
                        style={{
                          padding: "8px 0",
                          borderTop: "1px solid #f0f0f0",
                          marginTop: "8px",
                        }}
                      >
                        <div
                          style={{
                            fontSize: "11px",
                            fontWeight: "600",
                            color: "#333",
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
                                color: "#666",
                                marginBottom: "2px",
                              }}
                            >
                              Blur Score: {Number(ef.blur_score).toFixed(2)}
                            </div>
                          )}
                        {typeof ef.tamper_score !== "undefined" &&
                          ef.tamper_score !== null && (
                            <div style={{ fontSize: "11px", color: "#666" }}>
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
                          background: "#e3f2fd",
                          color: "#1976d2",
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
                              background: "rgba(255, 152, 0, 0.1)",
                              border: "1px solid rgba(255, 152, 0, 0.3)",
                              borderRadius: "4px",
                              fontSize: "11px",
                            }}
                          >
                            <div
                              style={{
                                fontWeight: 600,
                                marginBottom: 2,
                                color: "#f57c00",
                              }}
                            >
                              Assignment Note:
                            </div>
                            <div style={{ color: "#666", lineHeight: 1.4 }}>
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
              <div className="card-title">Verification & Trust</div>
              <span
                className={`badge ${isReportVerified(report, mlPrediction) ? "b-green" : "b-orange"}`}
              >
                {isReportVerified(report, mlPrediction)
                  ? "Verified"
                  : report.verification_status === "pending"
                    ? "Pending"
                    : report.verification_status === "under_review"
                      ? "Under Review"
                      : report.verification_status === "rejected"
                        ? "Rejected"
                        : "Needs verification"}
              </span>
            </div>
            <div style={{ marginBottom: "12px" }}>
              {/* Report-level ML trust */}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  marginBottom: "4px",
                }}
              >
                <span style={{ fontSize: "11px", color: "var(--muted)" }}>
                  Report Trust Score
                </span>
                <span
                  style={{
                    fontFamily: '"Syne", sans-serif',
                    fontWeight: 800,
                    fontSize: "17px",
                    color: "var(--success)",
                  }}
                >
                  {mlPrediction
                    ? Math.round(mlPrediction.trust_score ?? 0)
                    : "—"}
                </span>
              </div>
              <div className="prog-bar" style={{ marginBottom: "8px" }}>
                <div
                  className="prog-fill"
                  style={{
                    width: `${
                      mlPrediction
                        ? Math.max(
                            0,
                            Math.min(100, mlPrediction.trust_score ?? 0),
                          )
                        : 0
                    }%`,
                    background: "var(--success)",
                  }}
                ></div>
              </div>

                            {mlLoading && (
                <div
                  style={{
                    fontSize: "10px",
                    color: "var(--muted)",
                    marginTop: 6,
                  }}
                >
                  Loading ML prediction…
                </div>
              )}
              {mlPrediction && !mlLoading && (
                <div
                  style={{
                    marginTop: 6,
                    fontSize: "10px",
                    color: "var(--muted)",
                  }}
                >
                  <div>
                    Label: <strong>{mlPrediction.prediction_label}</strong> ·
                    Confidence{" "}
                    {Math.round(normalizePercent(mlPrediction.confidence) || 0)}%
                  </div>
                  <div>
                    {mlPrediction.evaluated_at &&
                      formatLocalDateTime(mlPrediction.evaluated_at)}
                  </div>
                </div>
              )}

              <div style={{ marginTop: 12, padding: "10px", borderRadius: 8, background: "var(--surface2)", border: "1px solid var(--border2)" }}>
                <div style={{ fontSize: "12px", fontWeight: 700, marginBottom: 6 }}>Status Summary</div>
                <div style={{ fontSize: "11px", color: "var(--muted)" }}>
                  {getVerificationStatus(report, mlPrediction)}
                </div>
              </div>

              {report.flag_reason && (
                <div style={{ marginTop: 10, padding: "10px", borderRadius: 8, background: "rgba(255, 152, 0, 0.12)", border: "1px solid rgba(255, 152, 0, 0.35)" }}>
                  <div style={{ fontSize: "11px", fontWeight: 700, marginBottom: 4 }}>Flag reason</div>
                  <div style={{ fontSize: "11px", color: "var(--text)" }}>{friendlyFlagReason(report.flag_reason)}</div>
                </div>
              )}

              {report.reviews && report.reviews.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: "12px", fontWeight: 700, marginBottom: 6 }}>Review History</div>
                  <div style={{ display: "grid", gap: 6 }}>
                    {report.reviews.slice().reverse().map((review, index) => (
                      <div
                        key={review.review_id || index}
                        style={{
                          padding: "8px",
                          borderRadius: 6,
                          background: "var(--surface2)",
                          border: "1px solid var(--border2)",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px" }}>
                          <strong>
                            {review.decision === "confirmed"
                              ? "Confirmed"
                              : review.decision === "rejected"
                                ? "Rejected"
                                : review.decision}
                          </strong>
                          <span style={{ color: "var(--muted)" }}>
                            {review.reviewed_at ? formatLocalDateTime(review.reviewed_at) : "Unknown time"}
                          </span>
                        </div>
                        <div style={{ fontSize: "10px", color: "var(--muted)", marginTop: 2 }}>
                          By: {review.reviewer_name || "Officer"}
                        </div>
                        {review.review_note && (
                          <div style={{ fontSize: "10px", marginTop: 4 }}>
                            "{review.review_note}"
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {!isReportVerified(report, mlPrediction) && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: "12px", fontWeight: 700, marginBottom: 6 }}>
                    Verification Requirements
                  </div>
                  <div style={{ fontSize: "11px", color: "var(--muted)" }}>
                    {getVerificationRequirements(report, mlPrediction)}
                  </div>
                </div>
              )}

              <div style={{ marginTop: 12 }}>
                <div
                  style={{ fontSize: "12px", fontWeight: 800, marginBottom: 8 }}
                >
                  Credibility Breakdown
                </div>
                {trustFactors && Object.keys(trustFactors).length > 0 ? (
                  <div
                    style={{ display: "flex", flexDirection: "column", gap: 6 }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                      }}
                    >
                      <span style={{ fontSize: "11px", color: "var(--muted)" }}>
                        Content score
                      </span>
                      <span style={{ fontSize: "11px", fontWeight: 800 }}>
                        {trustFactors.content_score ?? "—"}
                      </span>
                    </div>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                      }}
                    >
                      <span style={{ fontSize: "11px", color: "var(--muted)" }}>
                        Location score
                      </span>
                      <span style={{ fontSize: "11px", fontWeight: 800 }}>
                        {trustFactors.location_score ?? "—"}
                      </span>
                    </div>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                      }}
                    >
                      <span style={{ fontSize: "11px", color: "var(--muted)" }}>
                        Cluster score
                      </span>
                      <span style={{ fontSize: "11px", fontWeight: 800 }}>
                        {trustFactors.cluster_score ?? "—"}
                      </span>
                    </div>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                      }}
                    >
                      <span style={{ fontSize: "11px", color: "var(--muted)" }}>
                        User behavior score
                      </span>
                      <span style={{ fontSize: "11px", fontWeight: 800 }}>
                        {trustFactors.user_behavior_score ?? "—"}
                      </span>
                    </div>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                      }}
                    >
                      <span style={{ fontSize: "11px", color: "var(--muted)" }}>
                        Community net votes
                      </span>
                      <span style={{ fontSize: "11px", fontWeight: 800 }}>
                        {trustFactors.community_net_votes ?? "—"}
                      </span>
                    </div>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                      }}
                    >
                      <span style={{ fontSize: "11px", color: "var(--muted)" }}>
                        Coordination penalty
                      </span>
                      <span style={{ fontSize: "11px", fontWeight: 800 }}>
                        {trustFactors.coordination_penalty ?? "—"}
                      </span>
                    </div>
                  </div>
                ) : (
                  <div style={{ fontSize: "10px", color: "var(--muted)" }}>
                    No breakdown available yet.
                  </div>
                )}
              </div>
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

      {/* Review Reason Modal */}
      {showReasonModal && (
        <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && setShowReasonModal(false)}>
          <div className="modal">
            <div className="modal-header">
              <div className="modal-title">
                {pendingDecision === "confirmed" ? "Verify Report" : "Flag Report"}
              </div>
              <div className="modal-close" onClick={() => setShowReasonModal(false)}>✕</div>
            </div>

            <div className="input-group">
              <div className="input-label">Reason *</div>
              <div style={{ fontSize: '11px', color: 'var(--muted)', marginBottom: '6px' }}>
                Please provide a reason for {pendingDecision === "confirmed" ? "verifying" : "flagging"} this report.
              </div>
              <textarea
                rows="4"
                placeholder={pendingDecision === "confirmed" 
                  ? "Explain why this report is verified and legitimate..." 
                  : "Explain why this report is being flagged..."
                }
                value={reviewReason}
                onChange={(e) => setReviewReason(e.target.value)}
                style={{ width: '100%', padding: '8px', border: '1px solid var(--border)', borderRadius: '4px' }}
              />
            </div>
            
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button 
                className="btn btn-outline" 
                onClick={() => setShowReasonModal(false)} 
                disabled={!!savingDecision}
              >
                Cancel
              </button>
              <button 
                className={`btn ${pendingDecision === "confirmed" ? "btn-success" : "btn-danger"}`} 
                onClick={confirmReview} 
                disabled={!reviewReason.trim() || !!savingDecision}
              >
                {savingDecision === pendingDecision 
                  ? (pendingDecision === "confirmed" ? "Verifying…" : "Flagging…")
                  : (pendingDecision === "confirmed" ? "Verify" : "Flag")
                }
              </button>
            </div>
          </div>
        </div>
      )}

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
              backgroundColor: 'rgba(59, 130, 246, 0.1)', 
              border: '1px solid rgba(59, 130, 246, 0.3)', 
              borderRadius: '6px', 
              marginBottom: '16px',
              fontSize: '12px',
              color: 'var(--text)'
            }}>
              <strong>📋 Filtering Rules:</strong>
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
                          📍 {case_item.location.location_name}
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
