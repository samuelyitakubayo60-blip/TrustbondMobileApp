/** Primary label for a case card (incident-based name, not CASE-0001). */
export function caseDisplayName(caseItem) {
  if (!caseItem) return 'Case';
  const title = (caseItem.title || caseItem.incident_type_name || '').trim();
  if (title) {
    if (/ case$/i.test(title)) return title;
    if (/ cases$/i.test(title)) return `${title.replace(/\s+Cases$/i, '')} case`;
    return `${title} case`;
  }
  return caseItem.case_number || String(caseItem.case_id || '').slice(0, 8) || 'Case';
}

/** Secondary line: internal case number for reference. */
export function caseDisplayRef(caseItem) {
  if (!caseItem?.case_number) return '';
  return caseItem.case_number;
}
