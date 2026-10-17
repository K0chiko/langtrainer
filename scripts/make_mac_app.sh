#!/bin/zsh
# Builds "Language Trainer.app": double-click to start the server and open the browser; quit it to stop the server.
# Usage: scripts/make_mac_app.sh [target-folder]   (default: ~/Applications)
set -e
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
TARGET="${1:-$HOME/Applications}"
APP="$TARGET/Language Trainer.app"

[ -x ".venv/bin/langtrainer" ] || { echo "Run 'uv sync' first: .venv/bin/langtrainer not found." >&2; exit 1; }
mkdir -p "$TARGET"
rm -rf "$APP"

# The server is started with a minimal PATH, so remember the folders where `claude`, `ffmpeg` etc. live now.
EXTRA_PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

SRC="$(mktemp -t langtrainer).applescript"
sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|" -e "s|__EXTRA_PATH__|$EXTRA_PATH|" launcher/macos/LanguageTrainer.applescript > "$SRC"
osacompile -s -o "$APP" "$SRC"   # -s: stay-open, so quitting from the Dock stops the server
rm -f "$SRC"
cp launcher/macos/icon.icns "$APP/Contents/Resources/applet.icns"   # replaces the default script-editor icon

PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleName string 'Language Trainer'" "$PLIST" 2>/dev/null || \
/usr/libexec/PlistBuddy -c "Set :CFBundleName 'Language Trainer'" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :NSMicrophoneUsageDescription string 'Language Trainer records your voice during conversations to find mistakes.'" "$PLIST" 2>/dev/null || true
# A stable signature lets macOS remember the microphone and screen-recording permissions for this app.
codesign --force --deep --sign - "$APP"
echo "Built: $APP"
