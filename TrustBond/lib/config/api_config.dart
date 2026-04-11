/// API base URL. Change via --dart-define when running, or edit the default below.
///
/// **Production:** Uses Render-hosted backend (auto-deployed from GitHub).
/// **Override:** flutter run --dart-define=API_BASE_URL=https://YOUR_URL/api/v1
class ApiConfig {
  /// Backend URL — deployed on Render.com (auto-deploys on git push).
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    // defaultValue: 'http://localhost:8000/api/v1',
    defaultValue: 'https://trustbondmobileapp.onrender.com/api/v1',
  );

  static String get devicesUrl => _url('$baseUrl/devices');
  static String get reportsUrl => _url('$baseUrl/reports');
  static String get incidentTypesUrl => _url('$baseUrl/incident-types');
  static String get publicLocationsUrl => _url('$baseUrl/public/locations');
  static String get publicLocationsGeoJsonUrl =>
      _url('$baseUrl/public/locations/geojson');

  static String _url(String url) {
    if (url.startsWith('http://') || url.startsWith('https://')) return url;
    return 'http://$url';
  }

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
