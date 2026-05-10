/** Human labels for separating police/AI verification from community (local leader) confirmation. */

export function formatTechnicalStatus(report) {
  const vs = (report?.verification_status || "").trim().toLowerCase();
  const rs = (report?.rule_status || "").trim().toLowerCase();
  const policeVerified = vs === "verified" || vs === "rejected";

  const aiParts = [];
  if (rs === "passed") aiParts.push("AI verification: passed");
  else if (rs === "flagged") aiParts.push("AI verification: needs review");
  else if (rs === "rejected") aiParts.push("AI verification: rejected");
  else if (rs === "pending") aiParts.push("AI verification: pending");

  // Police confirmation is the human / station step.
  const policeParts = [];
  if (vs === "under_review") policeParts.push("Police review: pending");
  else if (vs === "pending") policeParts.push("Police review: pending");
  else if (vs === "verified") {
    policeParts.push(report?.verified_by ? "Police confirmed" : "Auto-verified (AI)");
  } else if (vs === "rejected") {
    policeParts.push("Police rejected");
  }

  const parts = [...aiParts, ...policeParts].filter(Boolean);
  return parts.join(" · ") || "—";
}

export function formatCommunityConfirmation(report) {
  const ls = (report?.leader_verification_status || "").trim().toLowerCase();
  const leaderSubmitted =
    report?.submitted_by_local_leader_id != null &&
    report.submitted_by_local_leader_id !== "";

  if (leaderSubmitted && ls !== "rejected")
    return "Leader-submitted (auto community confirmation)";

  if (ls === "confirmed") return "Community confirmed (local leader)";
  if (ls === "rejected") return "Community not confirmed / disputed (leader)";
  if (!ls || ls === "pending")
    return "Awaiting community leader input (pending)";

  return ls.replaceAll("_", " ");
}

export function communityBadgeClass(report) {
  const ls = (report?.leader_verification_status || "").trim().toLowerCase();
  const leaderSubmitted = report?.submitted_by_local_leader_id != null;
  if (leaderSubmitted && ls !== "rejected") return "b-green";
  if (ls === "confirmed") return "b-green";
  if (ls === "rejected") return "b-red";
  return "b-orange";
}

/** Mirrors backend hotspot_auto._is_report_eligible (police + leader gate when enabled server-side). */
export function policeVerificationOkForHotspots(report) {
  const status = (report?.status || "").trim().toLowerCase();
  const verification = (report?.verification_status || "").trim().toLowerCase();
  const ruleStatus = (report?.rule_status || "").trim().toLowerCase();
  if (status === "rejected" || verification === "rejected" || ruleStatus === "rejected") {
    return { ok: false, reason: "rejected" };
  }
  const officerConfirmed =
    Array.isArray(report?.reviews) &&
    report.reviews.some((rv) => (rv.decision || "").trim().toLowerCase() === "confirmed");
  const policeOk =
    verification === "verified" || status === "verified" || officerConfirmed;
  return { ok: policeOk, reason: policeOk ? null : "police_pending" };
}

/** Mirrors backend leader_workflow.report_meets_leader_confirmation. */
export function leaderConfirmationOkForHotspots(report) {
  const st = (report?.leader_verification_status || "pending").trim().toLowerCase();
  if (st === "rejected") return false;
  return st === "confirmed";
}

/**
 * One-line UX cue for DPC / IO: why this row may be absent from safety-map hotspot clusters.
 * Server flags (leader gate, DPU requirement) can relax rules; copy stays accurate for default deployments.
 */
export function formatHotspotClusteringCue(report) {
  const pv = policeVerificationOkForHotspots(report);
  if (!pv.ok && pv.reason === "rejected") {
    return {
      excluded: true,
      text: "Hotspot clustering: not included (report rejected).",
    };
  }
  if (!pv.ok) {
    return {
      excluded: true,
      text:
        "Hotspot clustering: not included until police verification is complete (verification_status verified, report status verified, or officer review confirmed).",
    };
  }
  if (!leaderConfirmationOkForHotspots(report)) {
    const ls = (report?.leader_verification_status || "").trim().toLowerCase();
    if (ls === "rejected") {
      return {
        excluded: true,
        text:
          "Hotspot clustering: not included when community confirmation is required (leader disputed).",
      };
    }
    return {
      excluded: true,
      text:
        "Hotspot clustering: not included while community confirmation is pending — many DPU deployments only cluster leader_verification_status = confirmed.",
    };
  }
  return {
    excluded: false,
    text:
      "Hotspot clustering: meets usual inputs (police verified + community confirmed for gated analytics). Exact behavior depends on server settings.",
  };
}

export const REPORT_QUEUE_PRESETS = {
  none: {
    label: "All reports (clear queue filters)",
    leader_confirmation: null,
    verification_status_filter: null,
    verification_status_in: null,
    hint:
      "No preset — use filters below. AI verification is separate from police confirmation; community confirmation is local-leader attestation (separate from both).",
  },
  awaiting_leader: {
    label: "Awaiting leader input (my jurisdiction)",
    leader_confirmation: "pending",
    verification_status_filter: null,
    verification_status_in: null,
    hint:
      "Saved search for DPC/IO: village/cell leaders have not confirmed community attestation yet. Station screening may still run in parallel.",
  },
  confirmed_screening: {
    label: "Leader confirmed · under police screening",
    leader_confirmation: "confirmed",
    verification_status_filter: "under_review",
    verification_status_in: null,
    hint:
      "For IO/DPC triage: community attestation done; incident still under officer or station screening (under_review).",
  },
  leader_rejected: {
    label: "Leader disputed / not confirmed",
    leader_confirmation: "rejected",
    verification_status_filter: null,
    verification_status_in: null,
    hint:
      "DPC/IO queue: leader flagged narrative mismatch or unreliability. Compare with technical screening before closing out.",
  },
  station_need_action: {
    label: "Station ops — police screening queue",
    leader_confirmation: null,
    verification_status_filter: null,
    verification_status_in: "pending,under_review",
    hint:
      "Station workload slice: verification_status pending or under_review (needs police action). Combine with location filters as needed.",
  },
  dpu_analytics_lens: {
    label: "DPU / safety analytics lens — leader confirmed only",
    leader_confirmation: "confirmed",
    verification_status_filter: null,
    verification_status_in: null,
    hint:
      "Aligns with gated DPU and sector views when the backend requires leader_verification_status = confirmed (same gate as many hotspot runs).",
  },
};
