plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
    id("com.google.gms.google-services")
}

android {
    namespace = "com.example.mobile"

    // ── Pinned SDK versions ───────────────────────────────────────────────────
    // Hardcoded so a Flutter SDK upgrade never silently increases APK size.
    // Update only intentionally and re-verify release APK size stays ≤ 65 MB.
    compileSdk = 36
    ndkVersion = "28.2.13676358"

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
        isCoreLibraryDesugaringEnabled = true
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        applicationId = "com.example.mobile"
        minSdk = 24          // Android 7.0 — all active phones from 2016+
        targetSdk = 36
        versionCode = flutter.versionCode
        versionName = flutter.versionName

        // Single ABI: arm64-v8a covers every Android phone from ~2015.
        // Removing this line would add armeabi-v7a/x86_64 and grow APK by ~60 %.
        ndk {
            abiFilters += setOf("arm64-v8a")
        }

        // Strip all locale resources except English.
        // The app has no translated strings, so non-English res are dead weight.
        resourceConfigurations += setOf("en")
    }

    buildTypes {
        release {
            // R8 full-mode minification + resource shrinking + icon tree-shaking
            // are the three biggest contributors to keeping release APK ≤ 65 MB.
            // Do NOT disable these flags.
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = signingConfigs.getByName("debug")
        }
        debug {
            isMinifyEnabled = false
            isShrinkResources = false
        }
    }
}

dependencies {
    // Pinned: do not bump desugar_jdk_libs without re-checking release APK size.
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.4")
    implementation(platform("com.google.firebase:firebase-bom:32.7.0"))
    implementation("com.google.firebase:firebase-messaging")
    // firebase-analytics intentionally excluded — adds ~2 MB; add back only if needed.
}

flutter {
    source = "../.."
}
