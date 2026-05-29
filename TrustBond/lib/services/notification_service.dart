import 'dart:async';
import 'dart:convert';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:permission_handler/permission_handler.dart';

import 'api_service.dart';
import 'device_service.dart';
import 'leader_service.dart';
import 'platform_service.dart';

/// Mobile FCM push (citizens + local leaders). Police use the web dashboard only.
class NotificationService {
  static final NotificationService _instance = NotificationService._internal();
  factory NotificationService() => _instance;
  NotificationService._internal();

  final FlutterLocalNotificationsPlugin _localNotifications =
      FlutterLocalNotificationsPlugin();

  /// Only touch Firebase Messaging on Android/iOS after [Firebase.initializeApp].
  FirebaseMessaging? get _messaging =>
      PlatformService.supportsFirebase ? FirebaseMessaging.instance : null;

  // Notification stream controllers
  final StreamController<RemoteMessage> _messageStreamController =
      StreamController<RemoteMessage>.broadcast();
  Stream<RemoteMessage> get messageStream => _messageStreamController.stream;

  final StreamController<String> _leaderDeepLinkController =
      StreamController<String>.broadcast();
  Stream<String> get leaderDeepLinkStream => _leaderDeepLinkController.stream;

  final StreamController<String> _citizenReportDeepLinkController =
      StreamController<String>.broadcast();
  Stream<String> get citizenReportDeepLinkStream =>
      _citizenReportDeepLinkController.stream;

  String? _pendingLeaderReportId;
  String? _pendingCitizenReportId;

  bool _isInitialized = false;
  int _unreadCount = 0;
  final StreamController<int> _unreadCountController =
      StreamController<int>.broadcast();
  String? _fcmToken;

  Stream<int> get unreadCountStream => _unreadCountController.stream;
  int get unreadCount => _unreadCount;

  void markAllRead() {
    _unreadCount = 0;
    if (!_unreadCountController.isClosed) _unreadCountController.add(0);
  }

  /// Initialize Firebase Messaging and local notifications (mobile only).
  Future<void> initialize() async {
    if (_isInitialized) return;

    if (!PlatformService.supportsFirebase) {
      if (kDebugMode) {
        debugPrint('Firebase notifications not supported on this platform');
      }
      _isInitialized = true;
      return;
    }

    final messaging = _messaging;
    if (messaging == null) {
      _isInitialized = true;
      return;
    }

    try {
      await messaging.requestPermission(
        alert: true,
        announcement: false,
        badge: true,
        carPlay: false,
        criticalAlert: false,
        provisional: false,
        sound: true,
      );

      _fcmToken = await messaging.getToken();
      debugPrint('FCM Token: $_fcmToken');
      await _syncPushTokenWithBackend();

      messaging.onTokenRefresh.listen((newToken) async {
        _fcmToken = newToken;
        await _syncPushTokenWithBackend();
      });

      await _initializeLocalNotifications();

      FirebaseMessaging.onMessage.listen(_handleForegroundMessage);
      FirebaseMessaging.onMessageOpenedApp.listen(_handleMessageOpenedApp);
      FirebaseMessaging.onBackgroundMessage(_firebaseMessagingBackgroundHandler);

      final initialMessage = await messaging.getInitialMessage();
      if (initialMessage != null) {
        _handleMessageOpenedApp(initialMessage);
      }

      _isInitialized = true;
      debugPrint('NotificationService initialized successfully');
    } catch (e) {
      debugPrint('Failed to initialize NotificationService: $e');
    }
  }

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

  String? consumePendingLeaderReportId() {
    final id = _pendingLeaderReportId;
    _pendingLeaderReportId = null;
    return id;
  }

  void _dispatchLeaderDeepLink(RemoteMessage message) {
    final type = message.data['type']?.toString();
    if (type != 'leader_new_report') return;
    final reportId = message.data['report_id']?.toString().trim();
    if (reportId == null || reportId.isEmpty) return;
    _pendingLeaderReportId = reportId;
    if (!_leaderDeepLinkController.isClosed) {
      _leaderDeepLinkController.add(reportId);
    }
  }

  void _dispatchCitizenDeepLink(RemoteMessage message) {
    final type = message.data['type']?.toString();
    if (type != 'report_status_update') return;
    final reportId = message.data['report_id']?.toString().trim();
    if (reportId == null || reportId.isEmpty) return;
    _pendingCitizenReportId = reportId;
    if (!_citizenReportDeepLinkController.isClosed) {
      _citizenReportDeepLinkController.add(reportId);
    }
  }

  void _dispatchMobileDeepLink(RemoteMessage message) {
    _dispatchLeaderDeepLink(message);
    _dispatchCitizenDeepLink(message);
  }

  String? consumePendingCitizenReportId() {
    final id = _pendingCitizenReportId;
    _pendingCitizenReportId = null;
    return id;
  }

  Future<void> _syncPushTokenWithBackend() async {
    final token = _fcmToken?.trim();
    if (token == null || token.isEmpty) return;

    // Leader FCM — retry up to 3 times with back-off so a transient network
    // error at startup doesn't permanently silence leader notifications.
    try {
      final leaderTok = await LeaderService().getToken();
      if (leaderTok != null && leaderTok.trim().isNotEmpty) {
        bool registered = false;
        for (int attempt = 1; attempt <= 3 && !registered; attempt++) {
          try {
            await LeaderService().registerFcmToken(fcmToken: token);
            registered = true;
          } catch (e) {
            debugPrint('Leader FCM register attempt $attempt failed: $e');
            if (attempt < 3) {
              await Future.delayed(Duration(seconds: attempt * 2));
            }
          }
        }
        if (!registered) {
          debugPrint('Leader FCM registration failed after 3 attempts');
        }
      }
    } catch (e) {
      debugPrint('Leader FCM check failed: $e');
    }

    // Citizen device FCM — single attempt (token refresh will retry later).
    try {
      final deviceId = await DeviceService().ensureDeviceId();
      if (deviceId != null && deviceId.isNotEmpty) {
        await ApiService().registerMobileFcmToken(deviceId: deviceId, token: token);
      }
    } catch (e) {
      debugPrint('Citizen FCM register failed: $e');
    }
  }

  void _handleForegroundMessage(RemoteMessage message) {
    debugPrint('Received foreground message: ${message.messageId}');
    _messageStreamController.add(message);
    _dispatchMobileDeepLink(message);
    _unreadCount++;
    if (!_unreadCountController.isClosed) {
      _unreadCountController.add(_unreadCount);
    }
    _showLocalNotification(message);
  }

  void _handleMessageOpenedApp(RemoteMessage message) {
    debugPrint('App opened from notification: ${message.messageId}');
    _messageStreamController.add(message);
    _dispatchMobileDeepLink(message);
  }

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

    final payload = jsonEncode(message.data);
    await _localNotifications.show(
      message.hashCode,
      message.notification?.title ?? 'TrustBond',
      message.notification?.body ?? 'New notification',
      details,
      payload: payload,
    );
  }

  void _onNotificationTapped(NotificationResponse response) {
    debugPrint('Notification tapped: ${response.payload}');
    final raw = response.payload;
    if (raw == null || raw.isEmpty) return;
    try {
      final data = jsonDecode(raw);
      if (data is Map) {
        final type = data['type']?.toString();
        final reportId = data['report_id']?.toString().trim();
        if (reportId == null || reportId.isEmpty) return;
        if (type == 'leader_new_report') {
          _pendingLeaderReportId = reportId;
          if (!_leaderDeepLinkController.isClosed) {
            _leaderDeepLinkController.add(reportId);
          }
        } else if (type == 'report_status_update') {
          _pendingCitizenReportId = reportId;
          if (!_citizenReportDeepLinkController.isClosed) {
            _citizenReportDeepLinkController.add(reportId);
          }
        }
      }
    } catch (_) {}
  }

  Future<bool> requestPermissions() async {
    if (!PlatformService.supportsFirebase) return false;
    try {
      final notificationStatus = await Permission.notification.request();
      return notificationStatus.isGranted;
    } catch (e) {
      debugPrint('Failed to request notification permissions: $e');
      return false;
    }
  }

  Future<void> enableNotifications() async {
    if (!PlatformService.supportsFirebase) return;

    final hasPermission = await requestPermissions();
    if (!hasPermission) {
      throw Exception('Notification permissions denied');
    }

    if (!_isInitialized) {
      await initialize();
    }
  }

  Future<void> disableNotifications() async {
    if (!PlatformService.supportsFirebase) return;
    final messaging = _messaging;
    if (messaging == null) return;
    await messaging.deleteToken();
    _fcmToken = null;
  }

  Future<void> subscribeToTopic(String topic) async {
    if (!PlatformService.supportsFirebase) return;
    final messaging = _messaging;
    if (messaging == null) return;
    await messaging.subscribeToTopic(topic);
    debugPrint('Subscribed to topic: $topic');
  }

  Future<void> unsubscribeFromTopic(String topic) async {
    if (!PlatformService.supportsFirebase) return;
    final messaging = _messaging;
    if (messaging == null) return;
    await messaging.unsubscribeFromTopic(topic);
    debugPrint('Unsubscribed from topic: $topic');
  }

  String? get fcmToken => _fcmToken;

  Future<String?> refreshToken() async {
    if (!PlatformService.supportsFirebase) return null;
    final messaging = _messaging;
    if (messaging == null) return null;
    await messaging.deleteToken();
    _fcmToken = await messaging.getToken();
    debugPrint('FCM Token refreshed: $_fcmToken');
    await _syncPushTokenWithBackend();
    return _fcmToken;
  }

  void dispose() {
    _unreadCountController.close();
    _messageStreamController.close();
    _leaderDeepLinkController.close();
    _citizenReportDeepLinkController.close();
  }
}

@pragma('vm:entry-point')
Future<void> _firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  try {
    await Firebase.initializeApp();
  } catch (_) {}
  debugPrint('Handling background message: ${message.messageId}');
}

class NotificationTopics {
  static const String hotspotAlerts = 'hotspot_alerts';
  static const String reportUpdates = 'report_updates';
  static const String emergencyAlerts = 'emergency_alerts';
  static const String systemUpdates = 'system_updates';
}
