#!/usr/bin/env bash
# gen-pipl.sh — Generate binary PiPL resource from plugin.json
#
# Uses the pipl_gen Python tool (from Adobe/Bloks) to produce a raw binary
# .rsrc file that gets linked into the plugin via -sectcreate.
#
# Usage: ./scripts/gen-pipl.sh
# Output: resources/pipl.rsrc

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PLUGIN_DIR/tools/pipl_gen"

python3 -c "
from pipl_gen import pipl

p = pipl()
p.add_plugin_entry('PluginMain')
p.add_plugin_name('IllTool Overlay')
p.add_plugin_stsp(0)
p.generate_pipl_bin('$PLUGIN_DIR/resources/pipl.rsrc')
print('Generated pipl.rsrc')
"

echo "PiPL resource: $PLUGIN_DIR/resources/pipl.rsrc"
ls -la "$PLUGIN_DIR/resources/pipl.rsrc"
