#!/bin/sh
# Installe le lanceur de l'interface Qt dans le menu des applications.
# Usage : desktop/install-desktop.sh [--autostart]   (--autostart : lancement à l'ouverture de session)
#         desktop/install-desktop.sh --uninstall
set -e
DIR=$(cd "$(dirname "$0")/.." && pwd)
DATA=${XDG_DATA_HOME:-$HOME/.local/share}
CONFIG=${XDG_CONFIG_HOME:-$HOME/.config}
APP=$DATA/applications/claude-usage.desktop
ICON=$DATA/icons/hicolor/scalable/apps/claude-usage.svg
AUTOSTART=$CONFIG/autostart/claude-usage.desktop

if [ "$1" = "--uninstall" ]; then
    rm -f "$APP" "$ICON" "$AUTOSTART"
    echo "Lanceur désinstallé."
    exit 0
fi

# Commande installée par pip si elle existe, sinon le script du dépôt
if command -v claude-usage-gui >/dev/null 2>&1; then
    EXEC=$(command -v claude-usage-gui)
else
    EXEC="python3 $DIR/claude_usage_qt.py"
fi

mkdir -p "$(dirname "$APP")" "$(dirname "$ICON")"
cp "$DIR/desktop/claude-usage.svg" "$ICON"
sed "s|@EXEC@|$EXEC|" "$DIR/desktop/claude-usage.desktop.in" > "$APP"
echo "Lanceur installé : $APP"

if [ "$1" = "--autostart" ]; then
    mkdir -p "$(dirname "$AUTOSTART")"
    cp "$APP" "$AUTOSTART"
    echo "Démarrage automatique activé : $AUTOSTART"
fi
