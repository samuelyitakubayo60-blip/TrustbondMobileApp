// Firebase options for mobile FCM. Desktop may call initializeApp once so the
// linked firebase_core plugin does not throw [core/no-app]; FCM is not used on desktop.
// ignore_for_file: type=lint
import 'package:firebase_core/firebase_core.dart' show FirebaseOptions;
import 'package:flutter/foundation.dart'
    show defaultTargetPlatform, kIsWeb, TargetPlatform;

class DefaultFirebaseOptions {
  static FirebaseOptions get currentPlatform {
    if (kIsWeb) {
      throw UnsupportedError('Firebase is not configured for web in TrustBond.');
    }
    switch (defaultTargetPlatform) {
      case TargetPlatform.android:
        return android;
      case TargetPlatform.iOS:
        return ios;
      case TargetPlatform.windows:
        return windows;
      default:
        throw UnsupportedError(
          'Firebase is only used on Android/iOS for push notifications.',
        );
    }
  }

  static const FirebaseOptions android = FirebaseOptions(
    apiKey: 'AIzaSyD-hNqzFqQjea2hEnKTgr6o2DjJJYNEPwo',
    appId: '1:660172900195:android:e207dd2defec59cd0eb556',
    messagingSenderId: '660172900195',
    projectId: 'trustbond-17e08',
    storageBucket: 'trustbond-17e08.firebasestorage.app',
  );

  static const FirebaseOptions ios = FirebaseOptions(
    apiKey: 'AIzaSyD-hNqzFqQjea2hEnKTgr6o2DjJJYNEPwo',
    appId: '1:660172900195:android:e207dd2defec59cd0eb556',
    messagingSenderId: '660172900195',
    projectId: 'trustbond-17e08',
    storageBucket: 'trustbond-17e08.firebasestorage.app',
  );

  /// Placeholder so Windows builds with firebase_core linked do not crash at startup.
  static const FirebaseOptions windows = FirebaseOptions(
    apiKey: 'AIzaSyD-hNqzFqQjea2hEnKTgr6o2DjJJYNEPwo',
    appId: '1:660172900195:web:trustbond-windows-desktop',
    messagingSenderId: '660172900195',
    projectId: 'trustbond-17e08',
    storageBucket: 'trustbond-17e08.firebasestorage.app',
  );
}
