import 'dart:async';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:permission_handler/permission_handler.dart';

/// Handles Firebase Cloud Messaging and local notifications
class NotificationService {
  static final NotificationService _instance = NotificationService._internal();
  factory NotificationService() => _instance;
  NotificationService._internal();

  final FirebaseMessaging _firebaseMessaging = FirebaseMessaging.instance;
  final FlutterLocalNotificationsPlugin _localNotifications = FlutterLocalNotificationsPlugin();
  
  // Notification stream controllers
  final StreamController<RemoteMessage> _messageStreamController = StreamController<RemoteMessage>.broadcast();
  Stream<RemoteMessage> get messageStream => _messageStreamController.stream;

  bool _isInitialized = false;
  String? _fcmToken;

  /// Initialize Firebase Messaging and local notifications
  Future<void> initialize() async {
    if (_isInitialized) return;

    // Skip Firebase initialization on Windows
    if (defaultTargetPlatform == TargetPlatform.windows) {
      if (kDebugMode) {
        debugPrint('Firebase notifications not supported on Windows');
      }
      return;
    }

    try {
      // Request permission for iOS
      await _firebaseMessaging.requestPermission(
        alert: true,
        announcement: false,
        badge: true,
        carPlay: false,
        criticalAlert: false,
        provisional: false,
        sound: true,
      );

      // Get FCM token
      _fcmToken = await _firebaseMessaging.getToken();
      debugPrint('FCM Token: $_fcmToken');

      // Initialize local notifications
      await _initializeLocalNotifications();

      // Set up message handlers
      FirebaseMessaging.onMessage.listen(_handleForegroundMessage);
      FirebaseMessaging.onMessageOpenedApp.listen(_handleMessageOpenedApp);
      FirebaseMessaging.onBackgroundMessage(_firebaseMessagingBackgroundHandler);

      // Get initial message if app was opened from notification
      final initialMessage = await _firebaseMessaging.getInitialMessage();
      if (initialMessage != null) {
        _handleMessageOpenedApp(initialMessage);
      }

      _isInitialized = true;
      debugPrint('NotificationService initialized successfully');
    } catch (e) {
      debugPrint('Failed to initialize NotificationService: $e');
    }
  }

  /// Initialize local notifications for Android
  Future<void> _initializeLocalNotifications() async {
    const androidSettings = AndroidInitializationSettings('@mipmap/ic_launcher');
    const iosSettings = DarwinInitializationSettings(
      requestAlertPermission: true,
      requestBadgePermission: true,
      requestSoundPermission: true,
    );
    
    const initSettings = InitializationSettings(
      android: androidSettings,
      iOS: iosSettings,
    );

    await _localNotifications.initialize(
      initSettings,
      onDidReceiveNotificationResponse: _onNotificationTapped,
    );
  }

  /// Handle foreground messages
  void _handleForegroundMessage(RemoteMessage message) {
    debugPrint('Received foreground message: ${message.messageId}');
    _messageStreamController.add(message);
    _showLocalNotification(message);
  }

  /// Handle message when app is opened from notification
  void _handleMessageOpenedApp(RemoteMessage message) {
    debugPrint('App opened from notification: ${message.messageId}');
    _messageStreamController.add(message);
  }

  /// Show local notification for foreground messages
  Future<void> _showLocalNotification(RemoteMessage message) async {
    const androidDetails = AndroidNotificationDetails(
      'trustbond_channel',
      'TrustBond Notifications',
      channelDescription: 'Security and report notifications from TrustBond',
      importance: Importance.high,
      priority: Priority.high,
      showWhen: true,
    );

    const iosDetails = DarwinNotificationDetails(
      presentAlert: true,
      presentBadge: true,
      presentSound: true,
    );

    const details = NotificationDetails(
      android: androidDetails,
      iOS: iosDetails,
    );

    await _localNotifications.show(
      message.hashCode,
      message.notification?.title ?? 'TrustBond',
      message.notification?.body ?? 'New notification',
      details,
      payload: message.data.toString(),
    );
  }

  /// Handle notification tap
  void _onNotificationTapped(NotificationResponse response) {
    debugPrint('Notification tapped: ${response.payload}');
    // Handle navigation based on notification payload
  }

  /// Request notification permissions
  Future<bool> requestPermissions() async {
    try {
      // Request notification permission
      final notificationStatus = await Permission.notification.request();
      
      return notificationStatus.isGranted;
    } catch (e) {
      debugPrint('Failed to request notification permissions: $e');
      return false;
    }
  }

  /// Get Android version (helper method)
  /// Enable notifications
  Future<void> enableNotifications() async {
    final hasPermission = await requestPermissions();
    if (!hasPermission) {
      throw Exception('Notification permissions denied');
    }
    
    if (!_isInitialized) {
      await initialize();
    }
  }

  /// Disable notifications
  Future<void> disableNotifications() async {
    // Unsubscribe from topics if needed
    await _firebaseMessaging.deleteToken();
    _fcmToken = null;
  }

  /// Subscribe to a topic
  Future<void> subscribeToTopic(String topic) async {
    await _firebaseMessaging.subscribeToTopic(topic);
    debugPrint('Subscribed to topic: $topic');
  }

  /// Unsubscribe from a topic
  Future<void> unsubscribeFromTopic(String topic) async {
    await _firebaseMessaging.unsubscribeFromTopic(topic);
    debugPrint('Unsubscribed from topic: $topic');
  }

  /// Get current FCM token
  String? get fcmToken => _fcmToken;

  /// Refresh FCM token
  Future<String?> refreshToken() async {
    await _firebaseMessaging.deleteToken();
    _fcmToken = await _firebaseMessaging.getToken();
    debugPrint('FCM Token refreshed: $_fcmToken');
    return _fcmToken;
  }

  /// Dispose resources
  void dispose() {
    _messageStreamController.close();
  }
}

/// Background message handler (top-level function)
@pragma('vm:entry-point')
Future<void> _firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  try {
    // Required on background isolate.
    await Firebase.initializeApp();
  } catch (_) {
    // ignore: avoid_catches_without_on_clauses
  }
  debugPrint('Handling background message: ${message.messageId}');
  // Handle background messages here
  // You can initialize Firebase if needed
}

/// Topic subscription constants for different notification types
class NotificationTopics {
  static const String hotspotAlerts = 'hotspot_alerts';
  static const String reportUpdates = 'report_updates';
  static const String emergencyAlerts = 'emergency_alerts';
  static const String systemUpdates = 'system_updates';
}
