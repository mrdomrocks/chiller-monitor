#!/bin/sh
# Remove the program files. Site profiles are left in place.
set -eu
DEST=${CHILLER_PREFIX:-"$HOME/.local/opt/chiller-monitor"}
rm -rf "$DEST"
rm -f "$HOME/.local/bin/chiller-monitor"
rm -f "$HOME/.local/share/applications/chiller-monitor.desktop"
echo "Chiller Monitor was removed."
echo "Site profiles are still in \${XDG_DATA_HOME:-\$HOME/.local/share}/chiller-monitor"
