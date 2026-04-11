DateTime parseApiDateTimeToLocal(String raw) {
  final s = raw.trim();
  if (s.isEmpty) return DateTime.now();

  final hasTimezone = s.endsWith('Z') || RegExp(r'[+-]\d{2}:\d{2}$').hasMatch(s);
  final normalized = hasTimezone ? s : '${s}Z';
  return DateTime.parse(normalized).toLocal();
}

String formatTimeAgo(DateTime dt) {
  final localDt = dt.toLocal();
  final diff = DateTime.now().difference(localDt);

  if (diff.inSeconds < 30) return 'just now';
  if (diff.isNegative) return 'just now';
  if (diff.inMinutes < 1) return '${diff.inSeconds}s ago';
  if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
  if (diff.inHours < 24) return '${diff.inHours}h ago';
  if (diff.inDays < 7) return '${diff.inDays}d ago';
  return '${localDt.month}/${localDt.day}';
}
