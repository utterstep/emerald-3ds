#!/bin/sh
# JP address of an EN symbol, or the symbol at a JP address.
#   jpaddr.sh SYMBOL...        rows of jp_syms.tsv (exact name; re:REGEX for a pattern)
#   jpaddr.sh 0x0812abcd       EN symbol whose JP counterpart contains this JP address
#   jpaddr.sh --en 0x0812abcd  EN symbol containing this EN address, with its JP address
exec python3 -I "$(dirname "$0")/bin/lookup.py" "$@"
