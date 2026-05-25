# Flutter wrapper — must keep
-keep class io.flutter.app.** { *; }
-keep class io.flutter.plugin.** { *; }
-keep class io.flutter.util.** { *; }
-keep class io.flutter.view.** { *; }
-keep class io.flutter.** { *; }
-keep class io.flutter.plugins.** { *; }

# Firebase Messaging
-keep class com.google.firebase.messaging.** { *; }
-keep class com.google.firebase.iid.** { *; }

# Kotlin
-keep class kotlin.** { *; }
-keep class kotlinx.** { *; }
-dontwarn kotlin.**

# Google Play Services
-keep class com.google.android.gms.** { *; }
-dontwarn com.google.android.gms.**

# Google Play Core (split install / deferred components) — not used, suppress R8 missing-class errors
-dontwarn com.google.android.play.core.**
-keep class com.google.android.play.core.** { *; }

# Suppress common harmless warnings
-dontwarn sun.misc.**
-dontwarn java.awt.**
