#!/bin/sh
# Run the pinned, isolated Blender 5.2.3 (portable, profile under .evidence/blender/user).
# Reinstalls the freshly built extension first.  Usage: Tools/blender.sh [blender args...]
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export BLENDER_USER_RESOURCES="$ROOT/.evidence/blender/user"
B="${BL_BLENDER:-$ROOT/.evidence/blender/blender-5.2.3-windows-x64/blender.exe}"
python "$ROOT/Tools/build_addon.py" >/dev/null || exit 1
"$B" -b --factory-startup --command extension install-file -r user_default -e "$ROOT"/dist/brutal_legend-*.zip >/dev/null 2>&1
exec "$B" -b --factory-startup "$@"
