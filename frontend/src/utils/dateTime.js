export function parseApiDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  const raw = String(value).trim();
  if (!raw) return null;

  const hasTimezone = /([zZ]|[+-]\d{2}:\d{2})$/.test(raw);
  const normalized = hasTimezone ? raw : `${raw}Z`;
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatRelativeTime(value) {
  const d = parseApiDate(value);
  if (!d) return '—';

  const diffMs = Date.now() - d.getTime();
  if (diffMs < 0) return 'just now';
  const sec = Math.floor(diffMs / 1000);
  if (sec < 30) return 'just now';
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hrs = Math.floor(min / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString();
}

export function formatLocalDate(value) {
  const d = parseApiDate(value);
  return d ? d.toLocaleDateString() : '—';
}

export function formatLocalDateTime(value) {
  const d = parseApiDate(value);
  return d ? d.toLocaleString() : '—';
}
