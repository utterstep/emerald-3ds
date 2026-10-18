#!/bin/sh
# JP disassembly of an EN function next to the EN one (names substituted through jp_syms.tsv).
#   jpdis.sh SYMBOL            EN listing, then JP listing
#   jpdis.sh SYMBOL --side     side by side, aligned (| differs, < EN only, > JP only)
#   jpdis.sh SYMBOL --diff     unified diff of the two listings (addresses left out)
#   jpdis.sh SYMBOL --jp       JP only;  --en: EN only
#   jpdis.sh --jp-range 0xSTART 0xEND   any JP range (e.g. JP-only code from DIFFERENCES.md)
exec python3 -I "$(dirname "$0")/bin/dis.py" "$@"
