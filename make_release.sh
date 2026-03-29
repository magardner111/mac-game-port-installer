#!/bin/bash
# Build a distributable DMG for GitHub Releases.
#
# Requirements:
#   brew install create-dmg
#
# Output: GamePortInstaller-<version>.dmg

set -e

VERSION=$(git describe --tags --abbrev=0 2>/dev/null || echo "0.1.0")
APP_NAME="Game Port Installer"
DMG_NAME="GamePortInstaller-${VERSION}.dmg"
STAGE_DIR="$(mktemp -d)/stage"
APP_DIR="${STAGE_DIR}/${APP_NAME}"

echo "Building release ${VERSION}..."

# ── Stage source files ────────────────────────────────────────────────────────
mkdir -p "${APP_DIR}/scrapers"

cp main.py installer.py games.py settings.py zelda3_config.py \
   requirements.txt pyproject.toml "${APP_DIR}/"
cp scrapers/__init__.py scrapers/base.py scrapers/github.py \
   scrapers/github_source.py scrapers/t3hd0gg.py "${APP_DIR}/scrapers/"

# ── Setup script (run once) ───────────────────────────────────────────────────
cat > "${APP_DIR}/Setup.command" << 'SETUP'
#!/bin/bash
cd "$(dirname "$0")"
echo "Installing Python dependencies..."
pip3 install --break-system-packages -r requirements.txt
echo ""
echo "Done! You can now run Game Port Installer.command to launch the app."
SETUP
chmod +x "${APP_DIR}/Setup.command"

# ── Launcher (double-click to run) ────────────────────────────────────────────
cat > "${APP_DIR}/Game Port Installer.command" << 'LAUNCHER'
#!/bin/bash
cd "$(dirname "$0")"
python3 main.py
LAUNCHER
chmod +x "${APP_DIR}/Game Port Installer.command"

# ── DMG ───────────────────────────────────────────────────────────────────────
if ! command -v create-dmg &> /dev/null; then
    echo "create-dmg not found. Install it with: brew install create-dmg"
    echo ""
    echo "Staged files are at: ${APP_DIR}"
    echo "You can zip them manually: zip -r ${DMG_NAME%.dmg}.zip '${APP_DIR}'"
    exit 1
fi

create-dmg \
    --volname "${APP_NAME} ${VERSION}" \
    --window-pos 200 120 \
    --window-size 540 360 \
    --icon-size 80 \
    --icon "${APP_NAME}" 150 180 \
    --hide-extension "${APP_NAME}" \
    "${DMG_NAME}" \
    "${STAGE_DIR}/"

echo ""
echo "✓ Release ready: ${DMG_NAME}"
