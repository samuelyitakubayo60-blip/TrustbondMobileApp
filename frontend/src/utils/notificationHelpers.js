/** Hotspot alerts may be type=hotspot or legacy type=system + related_entity_type=hotspot. */
export const isHotspotNotification = (n) => {
  if (!n) return false;
  const type = String(n.type || "").toLowerCase();
  const entity = String(n.related_entity_type || "").toLowerCase();
  if (type === "hotspot" || entity === "hotspot") return true;
  return /hotspot/i.test(String(n.title || ""));
};

export const notificationCategory = (n) => {
  if (!n) return "other";
  if (isHotspotNotification(n)) return "hotspot";
  const type = String(n.type || "").toLowerCase();
  if (type === "report" || type === "assignment" || type === "system") return type;
  return type || "other";
};
