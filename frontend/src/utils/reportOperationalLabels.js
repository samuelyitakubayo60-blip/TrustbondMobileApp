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
    if (report?.verified_by) {
      const name = (report?.verified_by_name || "").trim();
      const role = (report?.verified_by_role || "").trim();
      const who = [role, name].filter(Boolean).join(" · ");
      policeParts.push(who ? `Police confirmed (${who})` : "Police confirmed");
    } else {
      policeParts.push("Auto-verified (AI)");
    }
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

/** Mirrors backend leader_workflow.report_ready_for_cases_and_hotspots. */
export function reportReadyForCasesAndHotspots(report) {
  const pv = policeVerificationOkForHotspots(report);
  if (!pv.ok) return false;
  return leaderConfirmationOkForHotspots(report);
}

/**
 * Single operational state aligned with the police dashboard workflow diagram.
 * @returns {'eligible'|'leader_confirmed_police_pending'|'leader_rejected'|'awaiting_leader'|'police_review_queue'|'rejected'}
 */
export function getOperationalPipelineState(report) {
  const pv = policeVerificationOkForHotspots(report);
  const leaderOk = leaderConfirmationOkForHotspots(report);
  const ls = (report?.leader_verification_status || "pending").trim().toLowerCase();

  if (!pv.ok && pv.reason === "rejected") return "rejected";
  if (ls === "rejected") return "leader_rejected";
  if (pv.ok && leaderOk) return "eligible";
  if (!pv.ok && ls === "confirmed") return "leader_confirmed_police_pending";
  if (pv.ok && !leaderOk) return "awaiting_leader";
  return "police_review_queue";
}

const PIPELINE_META = {
  eligible: {
    label: "Cases & hotspots",
    badge: "b-green",
    hint: "Police/AI verified and local leader confirmed. Report can feed auto-cases and hotspot clustering.",
  },
  leader_confirmed_police_pending: {
    label: "Pending for ops",
    badge: "b-orange",
    hint: "Leader confirmed but police verification is not complete yet. Stays out of cases/hotspots until police verifies.",
  },
  leader_rejected: {
    label: "Out of cases/hotspots",
    badge: "b-red",
    hint: "Local leader did not confirm this report. Excluded from case formation and hotspot clustering.",
  },
  awaiting_leader: {
    label: "Awaiting leader",
    badge: "b-orange",
    hint: "Police/AI step passed or in progress; waiting for village/cell leader community confirmation.",
  },
  police_review_queue: {
    label: "Police review queue",
    badge: "b-orange",
    hint: "Needs police screening (AI under_review, pending, or flagged). Leader input may still be pending.",
  },
  rejected: {
    label: "Rejected",
    badge: "b-red",
    hint: "Report rejected by rules, AI threshold, or police. Not used for cases or hotspots unless overturned on review.",
  },
};

export function formatOperationalPipelineLabel(report) {
  const state = getOperationalPipelineState(report);
  return PIPELINE_META[state]?.label || "—";
}

export function operationalPipelineBadgeClass(report) {
  const state = getOperationalPipelineState(report);
  return PIPELINE_META[state]?.badge || "b-gray";
}

export function formatOperationalPipelineHint(report) {
  const state = getOperationalPipelineState(report);
  return PIPELINE_META[state]?.hint || "";
}

/** Compact gate checklist for list/detail UI. */
export function operationalGateChecklist(report) {
  const pv = policeVerificationOkForHotspots(report);
  const leaderOk = leaderConfirmationOkForHotspots(report);
  const ls = (report?.leader_verification_status || "pending").trim().toLowerCase();
  return [
    {
      key: "ai_police",
      label: "1. AI / police verification",
      done: pv.ok,
      detail: pv.ok
        ? "Verified (AI threshold or police review)"
        : pv.reason === "rejected"
          ? "Rejected"
          : "Pending — under_review or awaiting officer",
    },
    {
      key: "leader",
      label: "2. Local leader confirmation",
      done: leaderOk,
      detail:
        ls === "confirmed"
          ? "Community confirmed"
          : ls === "rejected"
            ? "Leader disputed"
            : "Awaiting village/cell leader",
    },
    {
      key: "ops",
      label: "3. Cases & hotspots",
      done: pv.ok && leaderOk,
      detail: reportReadyForCasesAndHotspots(report)
        ? "Eligible for auto-case and hotspot clustering"
        : "Blocked until both gates above pass",
    },
  ];
}

/**
 * One-line UX cue for DPC / IO: why this row may be absent from safety-map hotspot clusters.
 * Server flags (leader gate, DPU requirement) can relax rules; copy stays accurate for default deployments.
 */
export function formatHotspotClusteringCue(report) {
  if (reportReadyForCasesAndHotspots(report)) {
    return {
      excluded: false,
      text: "Cases & hotspots: eligible — police/AI verified and local leader confirmed.",
    };
  }
  const state = getOperationalPipelineState(report);
  if (state === "leader_confirmed_police_pending") {
    return {
      excluded: true,
      text: formatOperationalPipelineHint(report),
    };
  }
  return {
    excluded: true,
    text: formatOperationalPipelineHint(report),
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
  ready_for_ops: {
    label: "Ready for cases & hotspots (both gates)",
    leader_confirmation: "confirmed",
    verification_status_filter: "verified",
    verification_status_in: null,
    hint:
      "Leader confirmed and police verification_status verified — matches backend case/hotspot eligibility.",
  },
  leader_yes_police_pending: {
    label: "Leader confirmed · police still pending",
    leader_confirmation: "confirmed",
    verification_status_filter: null,
    verification_status_in: "pending,under_review",
    hint:
      "Community attestation done; report stays pending for operations until police verifies (diagram: stays pending for ops).",
  },
  leader_submitted: {
    label: "Filed by local leader (mobile attestation)",
    leader_confirmation: null,
    verification_status_filter: null,
    verification_status_in: null,
    submitted_by_leader: true,
    hint:
      "Incidents submitted from the leader app with mobile-only verification (no citizen AI scorecard).",
  },
};
