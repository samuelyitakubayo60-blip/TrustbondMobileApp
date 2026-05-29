#!/usr/bin/env bash
# ── TrustBond release build script ───────────────────────────────────────────
# Usage: bash build_release.sh
#
# Always use this script instead of running `flutter build apk --release`
# directly. It enforces consistent flags and checks the output size stays
# within the 65 MB budget.
# ─────────────────────────────────────────────────────────────────────────────

set -e

MAX_MB=65
APK="build/app/outputs/flutter-apk/app-release.apk"

echo "Building TrustBond release APK..."

flutter build apk \
  --release \
  --tree-shake-icons \
  --no-pub

if [ ! -f "$APK" ]; then
  echo "ERROR: APK not found at $APK"
  exit 1
fi

# Get size in bytes, then convert to MB
BYTES=$(wc -c < "$APK")
MB=$(echo "scale=1; $BYTES / 1048576" | bc)
LIMIT_BYTES=$((MAX_MB * 1048576))

echo ""
echo "Release APK: $APK"
echo "Size: ${MB} MB (limit: ${MAX_MB} MB)"

if [ "$BYTES" -gt "$LIMIT_BYTES" ]; then
  echo ""
  echo "SIZE LIMIT EXCEEDED: ${MB} MB > ${MAX_MB} MB"
  echo "Check for new large dependencies or assets before distributing."
  exit 1
else
  echo "Size OK: within ${MAX_MB} MB budget."
fi
