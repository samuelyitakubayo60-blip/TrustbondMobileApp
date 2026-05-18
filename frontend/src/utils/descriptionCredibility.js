/** Police dashboard helpers for description_credibility API fields. */

export function hasDescriptionCredibility(report) {
  if (!report) return false;
  if ((report.credibility_summary || "").trim()) return true;
  const meta = report.description_credibility;
  return meta && typeof meta === "object" && Object.keys(meta).length > 0;
}

export function descriptionCredibilityDetailLines(report) {
  if (!report) return [];
  const fromApi = report.credibility_detail_lines;
  if (Array.isArray(fromApi) && fromApi.length > 0) {
    return fromApi.filter((line) => String(line || "").trim());
  }
  const meta = report.description_credibility;
  if (!meta || typeof meta !== "object") return [];

  const lines = [];
  const wc = meta.word_count;
  const minW = meta.min_recommended_words ?? 15;
  if (wc != null) {
    lines.push(`Reporter text: ${wc} words (recommended ${minW}+ for full credit)`);
  }
  if (meta.length_adjustment === "bonus") {
    const pts = meta.length_points;
    lines.push(
      pts != null
        ? `Longer description added +${pts} credibility points`
        : "Longer description improved credibility",
    );
  } else if (meta.length_adjustment === "penalty") {
    const applied = meta.applied_penalty_points;
    lines.push(
      applied != null
        ? `Short description reduced credibility by ${applied} points`
        : "Short description lowered credibility",
    );
  }
  if (meta.short_description_rescue) {
    const sem = meta.semantic_similarity;
    const semTxt =
      typeof sem === "number" ? ` (semantic match ${Math.round(sem)}%)` : "";
    lines.push(
      `Short text accepted: matches incident type and evidence${semTxt} (penalty capped at 30%)`,
    );
  } else if (meta.partial_rescue === "semantic_only") {
    lines.push(
      "Description matches incident type but needs evidence for full short-text credit",
    );
  }
  if (
    meta.semantic_similarity != null &&
    !meta.short_description_rescue
  ) {
    lines.push(
      `Description vs incident semantic match: ${Math.round(Number(meta.semantic_similarity))}%`,
    );
  }
  const evidenceCount = Number(report.evidence_count ?? 0);
  if (evidenceCount > 0) {
    lines.push(`Evidence files attached: ${evidenceCount}`);
  } else if (meta.has_evidence === false) {
    lines.push("No evidence files — short descriptions are penalized more");
  }
  return lines;
}
