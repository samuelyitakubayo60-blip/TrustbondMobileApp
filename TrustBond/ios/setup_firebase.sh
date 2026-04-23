#!/bin/bash

echo "Setting up Firebase for iOS..."

# Check if CocoaPods is installed
if ! command -v pod &> /dev/null; then
    echo "CocoaPods is not installed. Installing..."
    sudo gem install cocoapods
fi

# Navigate to iOS directory
cd ios

# Install Firebase pods
echo "Installing Firebase pods..."
pod install

# Update project if needed
echo "Updating pods..."
pod update

echo "Firebase iOS setup complete!"
echo ""
echo "Next steps:"
echo "1. Download GoogleService-Info.plist from Firebase Console"
echo "2. Place it in ios/Runner/GoogleService-Info.plist"
echo "3. Run 'flutter run' on an iOS device or simulator"
