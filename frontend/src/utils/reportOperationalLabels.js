/** Human labels for separating police/AI verification from community (local leader) confirmation. */

export function formatTechnicalStatus(report) {
  const vs = (report?.verification_status || "").trim().toLowerCase();
  const st = (report?.status || "").trim().toLowerCase();
  const rs = (report?.rule_status || "").trim().toLowerCase();
  const verified = !!report?.verified_at;
  const parts = [];
  if (vs)
    parts.push(
      vs === "under_review"
        ? "Police screening: Under review"
        : `Police verification: ${vs.replaceAll("_", " ")}`,
    );
  else if (st || rs) parts.push(`Report status: ${st || rs || "—"}`);
  if (verified) parts.push("Officer action recorded");
  return parts.filter(Boolean).join(" · ") || "—";
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

export const REPORT_QUEUE_PRESETS = {
  none: {
    label: "All reports (clear queue filters)",
    leader_confirmation: null,
    verification_status_filter: null,
    verification_status_in: null,
    hint:
      "No queue preset — use dropdowns below. Technical status reflects police screening and AI; community shows local-leader confirmation (separate from screening).",
  },
  awaiting_leader: {
    label: "Awaiting leader input",
    leader_confirmation: "pending",
    verification_status_filter: null,
    verification_status_in: null,
    hint:
      "Reports where village/cell leaders have not yet confirmed community attestation (status blank, pending). Police screening may still run in parallel.",
  },
  confirmed_screening: {
    label: "Leader confirmed · under police screening",
    leader_confirmation: "confirmed",
    verification_status_filter: "under_review",
    verification_status_in: null,
    hint:
      "Community attestation complete; incident is actively under officer / station screening.",
  },
  leader_rejected: {
    label: "Leader disputed / not confirmed",
    leader_confirmation: "rejected",
    verification_status_filter: null,
    verification_status_in: null,
    hint:
      "Local leader flagged that the community narrative does not match or is unreliable. Review alongside technical screening outcomes.",
  },
  station_need_action: {
    label: "Station ops — screening queue",
    leader_confirmation: null,
    verification_status_filter: null,
    verification_status_in: "pending,under_review",
    hint:
      "Operational slice: reports still moving through verification_status pending or under_review (police workload). Combine with filters above as needed.",
  },
  dpu_analytics_lens: {
    label: "DPU lens — leader confirmed only",
    leader_confirmation: "confirmed",
    verification_status_filter: null,
    verification_status_in: null,
    hint:
      "Same filter used for analytics that require community confirmation: incidents with leader_verification_status=confirmed align with gated DPU / sector views when that policy is enabled on the backend.",
  },
};
