import UIKit
import UserNotifications
import Firebase
import FirebaseMessaging

@available(iOS 10, *)
extension AppDelegate: UNUserNotificationCenterDelegate {
  
  // Handle notification presentation when app is in foreground
  func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    willPresent notification: UNNotification,
    withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
  ) {
    let userInfo = notification.request.content.userInfo
    
    // Handle Firebase messages
    if let _ = userInfo["gcm.message_id"] {
      Messaging.messaging().appDidReceiveMessage(userInfo)
    }
    
    // Show notification when app is in foreground
    completionHandler([[.banner, .sound, .badge]])
  }
  
  // Handle notification tap
  func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    didReceive response: UNNotificationResponse,
    withCompletionHandler completionHandler: @escaping () -> Void
  ) {
    let userInfo = response.notification.request.content.userInfo
    
    // Handle Firebase messages
    if let _ = userInfo["gcm.message_id"] {
      Messaging.messaging().appDidReceiveMessage(userInfo)
    }
    
    // Handle notification tap - you can navigate to specific screens here
    print("Notification tapped: \(userInfo)")
    
    completionHandler()
  }
}

extension AppDelegate: MessagingDelegate {
  
  // Handle FCM token refresh
  func messaging(_ messaging: Messaging, didReceiveRegistrationToken fcmToken: String?) {
    print("Firebase registration token: \(String(describing: fcmToken))")
    
    // Send token to your server or store it locally
    if let token = fcmToken {
      // You can send this token to your backend server
      // or handle it as needed for your app
      print("FCM Token received: \(token)")
    }
  }
  
  // Handle remote messages when app is in foreground
  func messaging(_ messaging: Messaging, didReceive remoteMessage: MessagingRemoteMessage) {
    print("Received data message: \(remoteMessage.appData)")
  }
}
