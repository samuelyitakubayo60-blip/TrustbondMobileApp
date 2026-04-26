import 'package:flutter/foundation.dart' show kIsWeb, defaultTargetPlatform, TargetPlatform;
import 'package:flutter/foundation.dart' show kDebugMode, debugPrint;

/// Platform-specific service manager
class PlatformService {
  static bool get isMobile => 
      !kIsWeb && (defaultTargetPlatform == TargetPlatform.android || defaultTargetPlatform == TargetPlatform.iOS);
  
  static bool get isDesktop => 
      !kIsWeb && (defaultTargetPlatform == TargetPlatform.windows || 
                  defaultTargetPlatform == TargetPlatform.macOS || 
                  defaultTargetPlatform == TargetPlatform.linux);
  
  static bool get isWeb => kIsWeb;
  
  static bool get supportsPushNotifications => isMobile;
  
  static bool get supportsFirebase => isMobile;
}

/// Mock notification service for platforms that don't support Firebase
class MockNotificationService {
  static Future<void> initialize() async {
    if (kDebugMode) {
      debugPrint('Mock notification service initialized for non-mobile platform');
    }
  }
  
  static Future<void> enableNotifications() async {
    if (kDebugMode) {
      debugPrint('Mock: Notifications enabled (not supported on this platform)');
    }
  }
  
  static Future<void> disableNotifications() async {
    if (kDebugMode) {
      debugPrint('Mock: Notifications disabled');
    }
  }
  
  static Future<void> subscribeToTopic(String topic) async {
    if (kDebugMode) {
      debugPrint('Mock: Subscribed to topic $topic (not supported on this platform)');
    }
  }
  
  static Future<void> unsubscribeFromTopic(String topic) async {
    if (kDebugMode) {
      debugPrint('Mock: Unsubscribed from topic $topic');
    }
  }
}
