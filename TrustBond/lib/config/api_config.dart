/// API base URL — always points to the hosted backend.
/// Mobile app is not allowed to connect to a local backend.
class ApiConfig {
  static const String baseUrl =
      'https://samuelyitakubayo-trustbond-backend.hf.space/api/v1';

  static String get devicesUrl => _url('$baseUrl/devices');
  static String get reportsUrl => _url('$baseUrl/reports');
  static String get incidentTypesUrl => _url('$baseUrl/incident-types');
  static String get publicLocationsUrl => _url('$baseUrl/public/locations');
  static String get publicLocationsGeoJsonUrl =>
      _url('$baseUrl/public/locations/geojson');
  static String get leaderAuthUrl => _url('$baseUrl/leader-auth');
  static String get leaderUrl => _url('$baseUrl/leader');
  static String get notificationsUrl => _url('$baseUrl/notifications');

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
