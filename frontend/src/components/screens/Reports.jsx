import React, { useEffect, useState, useCallback } from "react";
import SkeletonTable from '../Common/SkeletonTable';
import api from "../../api/client";
import { formatLocalDate } from "../../utils/dateTime";
import { useAuth } from "../../context/AuthContext";
import {
  formatTechnicalStatus,
  formatCommunityConfirmation,
  communityBadgeClass,
  formatOperationalPipelineLabel,
  operationalPipelineBadgeClass,
  formatOperationalPipelineHint,
  REPORT_QUEUE_PRESETS,
} from "../../utils/reportOperationalLabels";
import ReportTrustScore from "../ReportTrustScore";

const friendlyFlagReason = (reason) => {
  const m = {
    evidence_time_mismatch: "Evidence captured too long before submission",
    stale_live_capture_timestamp: "Live-capture timestamp is too old",
    incident_description_mismatch:
      "Description does not match selected incident type",
    incident_text_mismatch:
      "Description does not match selected incident type",
    INCIDENT_TEXT_MISMATCH:
      "Description does not match selected incident type",
    description_evidence_mismatch:
      "Description, media, and incident type do not align",
    evidence_incident_mismatch:
      "Media does not support the selected incident type",
    threshold_low_score:
      "Credibility score too low to auto-confirm",
    ai_suspicious_review: "AI marked this report as suspicious",
    ai_uncertain_review: "AI result is uncertain; manual review needed",
    ai_detected_fake: "AI detected possible fake evidence",
    device_burst_reporting: "Too many reports from same device in a short time",
    duplicate_description_recent:
      "Repeated description from same device (possible spam)",
    no_description_with_evidence:
      "Evidence attached but description is missing",
    minimal_description: "Description is too short for reliable triage",
    high_severity_incident: "High-severity incident requires manual review",
  };
  if (!reason) return "";
  return m[reason] || reason.replaceAll("_", " ");
};

const Reports = ({
  onOpenReport,
  wsRefreshKey,
  initialStatusFilter = "all",
}) => {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const PAGE_SIZE = 20;
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState({
    items: [],
    total: 0,
    limit: PAGE_SIZE,
    offset: 0,
  });
  const [loading, setLoading] = useState(true);
  const [dashboardStats, setDashboardStats] = useState(null);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [searchText, setSearchText] = useState("");
  const [debouncedSearchText, setDebouncedSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState(initialStatusFilter);
  const [typeFilter, setTypeFilter] = useState("all");
  const [sectorFilter, setSectorFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [queuePreset, setQueuePreset] = useState("none");
  const [incidentTypes, setIncidentTypes] = useState([]);
  const [locations, setLocations] = useState([]);

  const queueConfig = REPORT_QUEUE_PRESETS[queuePreset] || REPORT_QUEUE_PRESETS.none;

  const loadFilters = () => {
    // Load incident types for Types dropdown
    // Only include inactive types if user is admin
    const incidentTypesUrl = isAdmin
      ? "/api/v1/incident-types/?include_inactive=true"
      : "/api/v1/incident-types/";

    api
      .get(incidentTypesUrl)
      .then((res) => setIncidentTypes(res || []))
      .catch(() => setIncidentTypes([]));
    // Load locations (sectors) – only sectors for dropdown
    api
      .get("/api/v1/locations/")
      .then((res) => {
        const sectors = (res || []).filter(
          (loc) => loc.location_type === "sector",
        );
        setLocations(sectors);
      })
      .catch(() => setLocations([]));
  };

  const buildQuery = () => {
    const params = new URLSearchParams();
    params.set("limit", String(pageSize));
    params.set("offset", String(offset));

    // Add search parameter if there's search text
    if (debouncedSearchText.trim()) {
      params.set("search", debouncedSearchText.trim());
    }

    if (statusFilter !== "all") {
      let statusValue = null;
      if (statusFilter === "pending") statusValue = "pending";
      if (statusFilter === "verified") statusValue = "verified";
      if (statusFilter === "flagged") statusValue = "flagged";
      if (statusValue) params.set("report_status", statusValue);
    }

    const qp = REPORT_QUEUE_PRESETS[queuePreset] || REPORT_QUEUE_PRESETS.none;
    if (qp.leader_confirmation)
      params.set("leader_confirmation", qp.leader_confirmation);
    if (qp.verification_status_filter)
      params.set("verification_status_filter", qp.verification_status_filter);
    if (qp.verification_status_in)
      params.set("verification_status_in", qp.verification_status_in);
    if (qp.submitted_by_leader === true)
      params.set("submitted_by_leader", "true");
    if (typeFilter !== "all") {
      params.set("incident_type_id", String(typeFilter));
    }
    if (sectorFilter !== "all") {
      params.set("sector_location_id", String(sectorFilter));
    }
    if (priorityFilter !== "all") {
      params.set("priority", String(priorityFilter));
    }
    if (fromDate) {
      params.set("from_date", new Date(fromDate).toISOString());
    }
    if (toDate) {
      // include the whole day by going to end of day
      const end = new Date(toDate);
      end.setHours(23, 59, 59, 999);
      params.set("to_date", end.toISOString());
    }
    return `/api/v1/reports/?${params.toString()}`;
  };

  const loadReports = () => {
    setLoading(true);
    api
      .get(buildQuery())
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  const loadDashboardStats = () => {
    api
      .get("/api/v1/stats/dashboard")
      .then((res) => {
        setDashboardStats(res);
      })
      .catch(() => {
        // If Dashboard API fails, continue with Reports API data
      });
  };

  useEffect(() => {
    setStatusFilter(initialStatusFilter || "all");
    setOffset(0);
  }, [initialStatusFilter]);

  // Debounce search text (500ms delay)
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearchText(searchText);
    }, 500);
    return () => clearTimeout(timer);
  }, [searchText]);

  useEffect(() => {
    loadFilters();
    loadReports();
    loadDashboardStats();
  }, [
    offset,
    wsRefreshKey,
    initialStatusFilter,
    pageSize,
    statusFilter,
    typeFilter,
    sectorFilter,
    priorityFilter,
    fromDate,
    toDate,
    debouncedSearchText,
    queuePreset,
  ]);

  // Reset offset when debounced search text changes
  useEffect(() => {
    setOffset(0);
  }, [debouncedSearchText]);

  let items = data.items || [];

  // Client-side text search (ID, type, location)
  if (searchText.trim()) {
    const q = searchText.trim().toLowerCase();
    items = items.filter((r) => {
      const id = (r.report_number || String(r.report_id)).toLowerCase();
      const type = (r.incident_type_name || "").toLowerCase();
      const loc = (r.village_name || "").toLowerCase();
      return id.includes(q) || type.includes(q) || loc.includes(q);
    });
  }
  const total = data.total || items.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.floor(offset / pageSize) + 1;
  const windowStart = Math.max(1, currentPage - 1);
  const windowEnd = Math.min(totalPages, windowStart + 2);
  const pageNumbers = [];
  for (let p = windowStart; p <= windowEnd; p += 1) pageNumbers.push(p);

  const goToPage = (page) => {
    const safePage = Math.min(Math.max(page, 1), totalPages);
    setOffset((safePage - 1) * pageSize);
  };

  const fromItem = total === 0 ? 0 : offset + 1;
  const toItem = Math.min(offset + (data.items?.length || 0), total);

  // Use Dashboard API stats for accurate counts, fall back to Reports API data
  const pending =
    dashboardStats?.pending ??
    items.filter(
      (r) => r.status === "pending" || r.verification_status === "under_review",
    ).length;
  const verified =
    dashboardStats?.verified ??
    items.filter((r) => r.status === "verified").length;
  const flagged =
    dashboardStats?.flagged ??
    items.filter((r) => r.status === "flagged" || r.status === "rejected")
      .length;
  const allReports = dashboardStats?.total_reports ?? total;

  return (
    <>
      {/* ── Reports header card ── */}
      <div
        className="card"
        style={{ marginBottom: 20, padding: "20px 24px 16px" }}
      >
        {/* Title + pipeline flow */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: 12,
            marginBottom: 16,
          }}
        >
          <div>
            <h2 style={{ margin: 0, marginBottom: 4, fontSize: 22 }}>Reports</h2>
            <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>
              Two gates required before a report feeds cases &amp; hotspots.
            </p>
          </div>

          {/* Pipeline steps */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            {[
              { label: "Citizen submits", cls: "ps-muted"  },
              { label: "AI verification", cls: "ps-blue"   },
              { label: "Leader confirms", cls: "ps-orange"  },
              { label: "Cases & hotspots", cls: "ps-green" },
            ].map((step, i, arr) => (
              <React.Fragment key={step.label}>
                <span className={`pipeline-step ${step.cls}`}>{step.label}</span>
                {i < arr.length - 1 && (
                  <span style={{ color: "var(--muted)", fontSize: 14 }}>→</span>
                )}
              </React.Fragment>
            ))}
          </div>
        </div>

        {/* Queue preset hint */}
        {queuePreset !== "none" && (
          <div
            style={{
              marginBottom: 14,
              padding: "10px 14px",
              borderRadius: 8,
              background: "var(--c-accent-dim)",
              border: "1px solid var(--c-accent-ring)",
              fontSize: 13,
              lineHeight: 1.5,
            }}
          >
            <strong>{queueConfig.label}</strong>
            <div style={{ marginTop: 4, color: "var(--muted)", fontSize: 12 }}>
              {queueConfig.hint}
            </div>
          </div>
        )}

        {/* Stats — clickable to filter */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
          {[
            { label: "All Reports",   value: allReports, cls: "sb-blue",   filter: "all"     },
            { label: "Pending review", value: pending,   cls: "sb-orange", filter: "pending"  },
            { label: "Verified",       value: verified,  cls: "sb-green",  filter: "verified" },
            { label: "Flagged",        value: flagged,   cls: "sb-red",    filter: "flagged"  },
          ].map((s) => (
            <button
              key={s.filter}
              onClick={() => { setStatusFilter(s.filter); setOffset(0); }}
              className={`stat-btn ${s.cls}${statusFilter === s.filter ? " active" : ""}`}
            >
              <div className="stat-btn-label">{s.label}</div>
              <div className="stat-btn-value">{s.value}</div>
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="filter-row">
          <select
            className="select"
            style={{ width: 'auto' }}
            value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value)); setOffset(0); }}
          >
            <option value={10}>10 / page</option>
            <option value={20}>20 / page</option>
            <option value={50}>50 / page</option>
          </select>
          <input
            className="input"
            placeholder="Search by ID, type, or location..."
            style={{ flex: 2, minWidth: "140px" }}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
          <select
            className="select"
            value={queuePreset}
            title="Saved-search presets for DPC / IO / station leads — filters only; no change to verification pipeline"
            onChange={(e) => {
              const v = e.target.value;
              setQueuePreset(v);
              setOffset(0);
              setStatusFilter("all");
            }}
          >
            {Object.entries(REPORT_QUEUE_PRESETS).map(([key, cfg]) => (
              <option key={key} value={key}>
                {cfg.label}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="all">All Statuses</option>
            <option value="pending">Pending</option>
            <option value="verified">Verified</option>
            <option value="flagged">Flagged</option>
          </select>
          <select
            className="select"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
          >
            <option value="all">All Types</option>
            {incidentTypes.map((t) => (
              <option key={t.incident_type_id} value={t.incident_type_id}>
                {t.type_name}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={sectorFilter}
            onChange={(e) => setSectorFilter(e.target.value)}
          >
            <option value="all">All Sectors</option>
            {locations.map((loc) => (
              <option key={loc.location_id} value={loc.location_id}>
                {loc.location_name}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
          >
            <option value="all">All Priorities</option>
            <option value="high">High priority</option>
            <option value="medium">Medium priority</option>
            <option value="low">Low priority</option>
          </select>
          <input
            className="input"
            type="date"
            style={{ minWidth: "130px" }}
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
          />
          <input
            className="input"
            type="date"
            style={{ minWidth: "130px" }}
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
          />

          <button
            className="btn btn-outline"
            onClick={() => {
              // Simple CSV export using current filtered results on the client
              if (!items.length) {
                window.alert("No reports to export.");
                return;
              }
              const header = [
                "report_number",
                "incident_type",
                "village",
                "trust_score",
                "technical_screening_summary",
                "community_leader_summary",
                "operational_status",
                "assignment_priority",
                "rule_status",
                "reported_at",
              ];
              const rows = items.map((r) => [
                r.report_number || String(r.report_id),
                r.incident_type_name || "",
                r.village_name || "",
                r.trust_score ?? "",
                formatTechnicalStatus(r),
                formatCommunityConfirmation(r),
                formatOperationalPipelineLabel(r),
                r.assignment_priority || "",
                r.rule_status ?? "",
                r.reported_at || "",
              ]);
              const csv = [
                header.join(","),
                ...rows.map((row) =>
                  row
                    .map((v) => `"${String(v).replace(/"/g, '""')}"`)
                    .join(","),
                ),
              ].join("\n");
              const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = "reports.csv";
              a.click();
              URL.revokeObjectURL(url);
            }}
          >
            Export CSV
          </button>
        </div>

        <div className="tbl-wrap">
          <table style={{ minWidth: 1180 }}>
            <thead>
              <tr>
                <th>#</th>
                <th>Report ID</th>
                <th>Type</th>
                <th>Location</th>
                <th>Trust Score</th>
                <th style={{ minWidth: 130, whiteSpace: "nowrap" }}>
                  AI Result
                </th>
                <th style={{ minWidth: 110, whiteSpace: "nowrap" }}>
                  Priority
                </th>
                <th style={{ minWidth: 180 }}>AI Verification</th>
                <th style={{ minWidth: 150 }}>Community (leader)</th>
                <th style={{ minWidth: 140 }}>Operational status</th>
                <th>Date</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r, index) => {
                const assignmentPriority = (
                  r.assignment_priority || ""
                ).toLowerCase();
                const reportPriority = (r.priority || "").toLowerCase();
                const shownPriority = assignmentPriority || reportPriority;
                const vs = (r.verification_status || "").toLowerCase();
                const rowNumber = offset + index + 1;
                return (
                  <tr key={r.report_id}>
                    <td
                      style={{
                        fontSize: "12px",
                        color: "var(--muted)",
                        textAlign: "center",
                      }}
                    >
                      {rowNumber}
                    </td>
                    <td style={{ fontSize: "10px", color: "var(--muted)" }}>
                      {r.report_number || String(r.report_id).slice(0, 8)}
                    </td>
                    <td>
                      <strong>{r.incident_type_name || "—"}</strong>
                    </td>
                    <td>{r.village_name || "—"}</td>
                    <td>
                      <ReportTrustScore report={r} />
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {r.ml_prediction_label ? (
                        <span
                          className={`badge ${
                            r.ml_prediction_label === "likely_real"
                              ? "b-green"
                              : r.ml_prediction_label === "suspicious" ||
                                  r.ml_prediction_label === "uncertain"
                                ? "b-orange"
                                : r.ml_prediction_label === "fake"
                                  ? "b-red"
                                  : "b-gray"
                          }`}
                        >
                          {r.ml_prediction_label === "likely_real"
                            ? "Likely real"
                            : r.ml_prediction_label === "suspicious"
                              ? "Suspicious"
                              : r.ml_prediction_label === "uncertain"
                                ? "Needs Review"
                                : r.ml_prediction_label === "fake"
                                  ? "Low Credibility"
                                  : "Unknown"}
                        </span>
                      ) : r.ml_predictions && r.ml_predictions.length > 0 ? (
                        (() => {
                          // Get the latest ML prediction
                          const latestPrediction = r.ml_predictions.reduce((latest, pred) => {
                            return (!latest || new Date(pred.evaluated_at) > new Date(latest.evaluated_at)) ? pred : latest;
                          }, null);
                          
                          const trustScore = latestPrediction ? parseFloat(latestPrediction.trust_score) : 0;
                          const hasLabel = latestPrediction && latestPrediction.prediction_label;
                          
                          if (hasLabel) {
                            // Show traditional ML prediction label
                            return (
                              <span
                                className={`badge ${
                                  latestPrediction.prediction_label === "likely_real"
                                    ? "b-green"
                                    : latestPrediction.prediction_label === "suspicious" ||
                                        latestPrediction.prediction_label === "uncertain"
                                      ? "b-orange"
                                      : latestPrediction.prediction_label === "fake"
                                        ? "b-red"
                                        : "b-gray"
                                }`}
                              >
                                {latestPrediction.prediction_label === "likely_real"
                                  ? "Likely real"
                                  : latestPrediction.prediction_label === "suspicious"
                                    ? "Suspicious"
                                    : latestPrediction.prediction_label === "uncertain"
                                      ? "Needs Review"
                                      : latestPrediction.prediction_label === "fake"
                                        ? "Low Credibility"
                                        : "Unknown"}
                              </span>
                            );
                          } else {
                            // Show text analysis
                            return (
                              <span
                                className={`badge ${
                                  trustScore >= 70
                                    ? "b-green"
                                    : trustScore >= 40
                                      ? "b-orange"
                                      : "b-red"
                                }`}
                              >
                                Text Analysis
                              </span>
                            );
                          }
                        })()
                      ) : (
                        <span className="badge b-gray">No ML</span>
                      )}
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {shownPriority ? (
                        <span
                          className={`badge ${
                            shownPriority === "urgent" ||
                            shownPriority === "high"
                              ? "b-red"
                              : shownPriority === "medium"
                                ? "b-orange"
                                : "b-gray"
                          }`}
                        >
                          {shownPriority}
                        </span>
                      ) : (
                        <span className="badge b-gray">—</span>
                      )}
                    </td>
                    <td style={{ verticalAlign: "top", fontSize: "11px" }}>
                      {vs ? (
                        <span
                          className={`badge ${
                            vs === "under_review"
                              ? "b-orange"
                              : vs === "pending"
                                ? "b-orange"
                                : vs === "verified"
                                  ? "b-green"
                                  : "b-red"
                          }`}
                          style={{ display: "inline-block", marginBottom: 6 }}
                        >
                          {vs === "under_review"
                            ? "Under review"
                            : vs === "pending"
                              ? "Pending"
                              : vs === "verified"
                                ? "AI verified"
                                : "Rejected"}
                        </span>
                      ) : (
                        <span className="badge b-gray">{r.status || "—"}</span>
                      )}
                      {r.flag_reason && (
                        <div style={{ marginTop: 6, fontSize: "10px", color: "var(--muted)", maxWidth: 220 }}>
                          {friendlyFlagReason(r.flag_reason)}
                        </div>
                      )}
                      <div style={{ marginTop: 8, fontSize: "10px", color: "var(--muted)" }}>
                        {formatTechnicalStatus(r)}
                      </div>
                    </td>
                    <td style={{ verticalAlign: "top", fontSize: "11px" }}>
                      <span className={`badge ${communityBadgeClass(r)}`} style={{ display: "inline-block", marginBottom: 6 }}>
                        {(r.leader_verification_status || "pending").replaceAll("_", " ") || "pending"}
                      </span>
                      <div style={{ color: "var(--muted)", lineHeight: 1.35 }}>
                        {formatCommunityConfirmation(r)}
                      </div>
                    </td>
                    <td style={{ verticalAlign: "top", fontSize: "11px" }}>
                      <span
                        className={`badge ${operationalPipelineBadgeClass(r)}`}
                        style={{ display: "inline-block", marginBottom: 6 }}
                      >
                        {formatOperationalPipelineLabel(r)}
                      </span>
                      <div style={{ color: "var(--muted)", lineHeight: 1.35, fontSize: "10px" }}>
                        {formatOperationalPipelineHint(r)}
                      </div>
                    </td>
                    <td style={{ fontSize: "10px", color: "var(--muted)" }}>
                      {formatLocalDate(r.reported_at)}
                    </td>
                    <td>
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={() => onOpenReport(r.report_id)}
                      >
                        View
                      </button>
                    </td>
                  </tr>
                );
              })}
              {!items.length && !loading && (
                <tr>
                  <td
                    colSpan={12}
                    style={{
                      fontSize: "12px",
                      color: "var(--muted)",
                      textAlign: "center",
                    }}
                  >
                    No reports found.
                  </td>
                </tr>
              )}
              {loading && <SkeletonTable cols={12} rows={8} />}
            </tbody>
          </table>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginTop: "14px",
            flexWrap: "wrap",
            gap: "8px",
          }}
        >
          <div style={{ fontSize: "12px", color: "var(--muted)" }}>
            Showing {fromItem}-{toItem} of {total} reports
          </div>
          <div className="pagination">
            <button
              type="button"
              className="page-btn"
              onClick={() => goToPage(currentPage - 1)}
              disabled={currentPage <= 1 || loading}
            >
              ‹
            </button>
            {pageNumbers.map((page) => (
              <button
                key={page}
                type="button"
                className={`page-btn ${currentPage === page ? "current" : ""}`}
                onClick={() => goToPage(page)}
                disabled={loading}
              >
                {page}
              </button>
            ))}
            <button
              type="button"
              className="page-btn"
              onClick={() => goToPage(currentPage + 1)}
              disabled={currentPage >= totalPages || loading}
            >
              ›
            </button>
          </div>
        </div>
      </div>
    </>
  );
};

export default Reports;
