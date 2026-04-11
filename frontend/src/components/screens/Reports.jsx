import React, { useEffect, useState, useCallback } from "react";
import api from "../../api/client";
import { formatLocalDate } from "../../utils/dateTime";
import { useAuth } from "../../context/AuthContext";

const friendlyFlagReason = (reason) => {
  const m = {
    evidence_time_mismatch: "Evidence captured too long before submission",
    stale_live_capture_timestamp: "Live-capture timestamp is too old",
    incident_description_mismatch:
      "Description does not match selected incident type",
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
  const [incidentTypes, setIncidentTypes] = useState([]);
  const [locations, setLocations] = useState([]);

  const loadFilters = () => {
    // Load incident types for Types dropdown
    // Only include inactive types if user is admin
    const incidentTypesUrl = isAdmin
      ? "/api/v1/incident-types?include_inactive=true"
      : "/api/v1/incident-types";

    api
      .get(incidentTypesUrl)
      .then((res) => setIncidentTypes(res || []))
      .catch(() => setIncidentTypes([]));
    // Load locations (sectors) – only sectors for dropdown
    api
      .get("/api/v1/locations")
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
      // Map UI labels to status values used by backend (using 'status' field now)
      let statusValue = null;
      if (statusFilter === "pending") statusValue = "pending";
      if (statusFilter === "verified") statusValue = "verified";
      if (statusFilter === "flagged") statusValue = "flagged";
      if (statusValue) params.set("status", statusValue);
    }
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
    return `/api/v1/reports?${params.toString()}`;
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
      <div className="page-header">
        <h2>Reports</h2>
        <p>
          All citizen-submitted incident reports — filter, sort, and take
          action.
        </p>
      </div>

      <div className="stats-row">
        <div className="stat-card c-blue">
          <div className="stat-label">All Reports</div>
          <div className="stat-value sv-blue">{allReports}</div>
        </div>
        <div className="stat-card c-orange">
          <div className="stat-label">Pending review</div>
          <div className="stat-value sv-orange">{pending}</div>
        </div>
        <div className="stat-card c-green">
          <div className="stat-label">Verified</div>
          <div className="stat-value sv-green">{verified}</div>
        </div>
        <div className="stat-card c-red">
          <div className="stat-label">Flagged</div>
          <div className="stat-value sv-red">{flagged}</div>
        </div>
      </div>

      <div className="card">
        <div className="filter-row">
          <input
            className="input"
            type="number"
            min="5"
            max="100"
            placeholder="Rows"
            style={{ minWidth: "80px" }}
            value={pageSize}
            onChange={(e) => {
              const newSize = Math.max(
                5,
                Math.min(100, parseInt(e.target.value) || 20),
              );
              setPageSize(newSize);
              setOffset(0);
            }}
          />
          <input
            className="input"
            placeholder="Search by ID, type, or location..."
            style={{ flex: 2, minWidth: "140px" }}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
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
                "assignment_priority",
                "rule_status",
                "reported_at",
              ];
              const rows = items.map((r) => [
                r.report_number || String(r.report_id),
                r.incident_type_name || "",
                r.village_name || "",
                r.trust_score ?? "",
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
          <table style={{ minWidth: 1040 }}>
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
                <th>Status</th>
                <th>Date</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r, index) => {
                const score = r.trust_score ?? 0;
                const width = Math.max(0, Math.min(100, Number(score)));
                const status = r.status;
                const assignmentPriority = (
                  r.assignment_priority || ""
                ).toLowerCase();
                const reportPriority = (r.priority || "").toLowerCase();
                const shownPriority = assignmentPriority || reportPriority;
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
                      <div className="trust-wrap">
                        <div className="trust-track">
                          <div
                            className="trust-fill"
                            style={{
                              width: `${width}%`,
                              background:
                                score >= 70
                                  ? "var(--success)"
                                  : score >= 40
                                    ? "var(--warning)"
                                    : "var(--danger)",
                            }}
                          ></div>
                        </div>
                        <div className="trust-val">{Math.round(score)}</div>
                      </div>
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
                    <td>
                      <span
                        className={`badge ${
                          status === "pending" || status === "under_review"
                            ? "b-orange"
                            : status === "verified"
                              ? "b-green"
                              : "b-red"
                        }`}
                      >
                        {status === "under_review" ? "pending" : status}
                      </span>
                      {r.flag_reason && (
                        <div
                          style={{
                            marginTop: 4,
                            fontSize: "10px",
                            color: "var(--muted)",
                            maxWidth: 220,
                          }}
                        >
                          {friendlyFlagReason(r.flag_reason)}
                        </div>
                      )}
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
                    colSpan={9}
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
              {loading && (
                <tr>
                  <td
                    colSpan={9}
                    style={{
                      fontSize: "12px",
                      color: "var(--muted)",
                      textAlign: "center",
                    }}
                  >
                    Loading...
                  </td>
                </tr>
              )}
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
