/// Helper methods for JSON parsing with null safety
class JsonHelpers {
  /// Safely parse a double from JSON value
  static double doubleFromJson(dynamic json, String key) {
    if (json == null) return 0.0;
    if (json is Map<String, dynamic>) {
      final value = json[key];
      if (value == null) return 0.0;
      if (value is double) return value;
      if (value is int) return value.toDouble();
      if (value is String) {
        return double.tryParse(value) ?? 0.0;
      }
    }
    return 0.0;
  }

  /// Safely parse an int from JSON value
  static int intFromJson(dynamic json, String key) {
    if (json == null) return 0;
    if (json is Map<String, dynamic>) {
      final value = json[key];
      if (value == null) return 0;
      if (value is int) return value;
      if (value is double) return value.toInt();
      if (value is String) {
        return int.tryParse(value) ?? 0;
      }
    }
    return 0;
  }

  /// Safely parse a string from JSON value
  static String stringFromJson(dynamic json, String key) {
    if (json == null) return '';
    if (json is Map<String, dynamic>) {
      final value = json[key];
      if (value == null) return '';
      return value.toString();
    }
    return '';
  }

  /// Safely parse a boolean from JSON value
  static bool boolFromJson(dynamic json, String key) {
    if (json == null) return false;
    if (json is Map<String, dynamic>) {
      final value = json[key];
      if (value == null) return false;
      if (value is bool) return value;
      if (value is String) {
        return value.toLowerCase() == 'true';
      }
      if (value is int) {
        return value != 0;
      }
    }
    return false;
  }

  /// Safely parse a list from JSON value
  static List<T> listFromJson<T>(
    dynamic json, 
    String key, 
    T Function(dynamic) fromJson,
  ) {
    if (json == null) return [];
    if (json is Map<String, dynamic>) {
      final value = json[key];
      if (value == null) return [];
      if (value is List) {
        return value.map((item) => fromJson(item)).toList();
      }
    }
    return [];
  }
}
