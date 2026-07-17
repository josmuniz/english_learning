#!/bin/bash
# Instala/desinstala los LaunchAgents del quiz forzado.
# Uso: ./install.sh [minutos 1-120]   (default 5)
#      ./install.sh --uninstall
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
AGENTS_DIR="$HOME/Library/LaunchAgents"
BACKEND_PLIST="$AGENTS_DIR/com.josemuniz.elearn-backend.plist"
QUIZ_PLIST="$AGENTS_DIR/com.josemuniz.elearn-quiz.plist"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl unload "$BACKEND_PLIST" 2>/dev/null || true
  launchctl unload "$QUIZ_PLIST" 2>/dev/null || true
  rm -f "$BACKEND_PLIST" "$QUIZ_PLIST"
  echo "✓ Agentes elearn desinstalados"
  exit 0
fi

MINUTES="${1:-5}"
if ! [[ "$MINUTES" =~ ^[0-9]+$ ]] || (( 10#$MINUTES < 1 || 10#$MINUTES > 120 )); then
  echo "Uso: $0 [minutos 1-120] | --uninstall" >&2
  exit 1
fi
INTERVAL=$(( 10#$MINUTES * 60 ))

mkdir -p "$AGENTS_DIR" "$HOME/Library/Logs"

# GEMINI_API_KEY para la generación de escenas: se inyecta al plist del backend
# (launchd no lee ~/.zshrc). El plist vive fuera del repo; la key no toca git.
GEMINI_KEY_XML=""
if [ -n "${GEMINI_API_KEY:-}" ]; then
  GEMINI_KEY_XML="<key>EnvironmentVariables</key><dict><key>GEMINI_API_KEY</key><string>${GEMINI_API_KEY}</string></dict>"
else
  echo "AVISO: GEMINI_API_KEY no está en el entorno; la generación de imágenes quedará deshabilitada en el backend de launchd." >&2
fi

cat > "$BACKEND_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.josemuniz.elearn-backend</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string>
    <string>$PROJECT_DIR/start.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
  ${GEMINI_KEY_XML}
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/elearn-backend.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/elearn-backend.log</string>
</dict></plist>
EOF

cat > "$QUIZ_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.josemuniz.elearn-quiz</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string>
    <string>$SCRIPT_DIR/quiz_dialog.py</string>
  </array>
  <key>StartInterval</key><integer>$INTERVAL</integer>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/elearn-quiz.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/elearn-quiz.log</string>
</dict></plist>
EOF

launchctl unload "$BACKEND_PLIST" 2>/dev/null || true
launchctl unload "$QUIZ_PLIST" 2>/dev/null || true
launchctl load "$BACKEND_PLIST"
launchctl load "$QUIZ_PLIST"

echo "✓ Backend: com.josemuniz.elearn-backend (KeepAlive, log: ~/Library/Logs/elearn-backend.log)"
echo "✓ Quiz:    com.josemuniz.elearn-quiz cada $MINUTES min (log: ~/Library/Logs/elearn-quiz.log)"
echo "  Desinstalar: $0 --uninstall"
