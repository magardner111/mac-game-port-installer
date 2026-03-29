#!/bin/bash
# Build Game Port Installer.app
set -e

echo "Cleaning previous build..."
rm -rf build dist

echo "Building with PyInstaller..."
pyinstaller GamePortInstaller.spec

echo ""
echo "✓ Build complete: dist/Game Port Installer.app"
echo ""

# Optional: create a distributable DMG
if command -v create-dmg &> /dev/null; then
    echo "Creating DMG..."
    create-dmg \
        --volname "Game Port Installer" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "Game Port Installer.app" 175 190 \
        --hide-extension "Game Port Installer.app" \
        --app-drop-link 425 190 \
        "dist/GamePortInstaller.dmg" \
        "dist/Game Port Installer.app"
    echo "✓ DMG created: dist/GamePortInstaller.dmg"
else
    echo "Tip: install create-dmg for a distributable DMG:"
    echo "     brew install create-dmg"
fi
