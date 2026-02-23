/// API base URL. Change via --dart-define when running, or edit the default below.
///
/// **Real phone (ngrok):**
/// 1. Start backend: cd backend && uvicorn app.main:app --reload --host 0.0.0.0
/// 2. Start ngrok: ngrok http 8000
/// 3. Copy the https URL (e.g. https://abc123.ngrok-free.app)
/// 4. Run app: flutter run --dart-define=API_BASE_URL=https://YOUR_NGROK_URL/api/v1
///
/// **Change it yourself:** Edit [baseUrl] below, or use --dart-define=API_BASE_URL=... when running.
class ApiConfig {
  /// Default: localhost (emulator/desktop). For real device use ngrok URL via --dart-define.
  /// Must include scheme (http:// or https://) so requests succeed.
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://localhost:8000/api/v1',
  );

  static String get devicesUrl => _url('$baseUrl/devices');
  static String get reportsUrl => _url('$baseUrl/reports');
  static String get incidentTypesUrl => _url('$baseUrl/incident-types');

  /// Ensure URL has a scheme so http client can connect.
  static String _url(String url) {
    if (url.startsWith('http://') || url.startsWith('https://')) return url;
    return 'http://$url';
  }

  /// Full URL for an evidence file (file_url from API may be relative).
  static String evidenceFileUrl(String fileUrl) {
    if (fileUrl.startsWith('http://') || fileUrl.startsWith('https://')) {
      return fileUrl;
    }
    final u = Uri.tryParse(baseUrl);
    final origin = (u != null && u.hasScheme)
        ? u.origin
        : 'http://${baseUrl.split('/').first}';
    return origin + (fileUrl.startsWith('/') ? fileUrl : '/$fileUrl');
  }
}
