# Assets

- **images/logo.jpeg** – TrustBond logo used for:
  - **Splash screen** (in-app and native splash)
  - **App launcher icon** (icon shown when installing and on the home screen)

For best launcher icon results, use a **square image** (e.g. 1024×1024 px). PNG is preferred; JPEG works.

**After changing the logo, regenerate:**
```bash
# Native splash (first screen when opening the app)
dart run flutter_native_splash:create

# App launcher icon (install / home screen icon)
dart run flutter_launcher_icons
```
