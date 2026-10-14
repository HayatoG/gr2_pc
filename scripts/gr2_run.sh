#!/usr/bin/env bash
# Gravity Rush 2: prepares the image, runs the game for N seconds and, optionally, presses buttons
# from a script and saves screenshots (raw RGBA display dumps converted to PNG).
# Usage: scripts/gr2_run.sh [seconds=120] [shots_dir] [press_script]
#   press_script: lines "<second> <buttons...>" (e.g. "40 cross", "60 options"); each press lasts 0.3 s.
# Only one game instance may run at a time on this machine: the script waits for any other.
set -uo pipefail
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
port=$root/port
seconds=${1:-120}; shots=${2:-}; script=${3:-}
dump=$root/game/CUSA03694
# One game instance at a time on this machine (shared lock with the other agents' runs).
lock=${GAME_LOCK:-/tmp/claude-1000/-home-hayatog-decomp/79f27d1d-d3f5-4a2e-a5f3-511e01385ae2/scratchpad/game.lock}
if [[ -z ${GR2_RUN_LOCKED:-} ]]; then
    touch "$lock"; exec env GR2_RUN_LOCKED=1 flock "$lock" "$0" "$@"
fi
(cd "$port/scripts" &&
 python3 prepare.py "$dump" --out ../out >/dev/null &&
 python3 link_modules.py "$dump" --out ../out --modules libc.prx libSceFios2.prx libSceJobManager.prx \
     "$dump/sysdata/libSceSecure.prx" "$root/dump/system_lib/libSceNgs2.sprx" >/dev/null &&
 python3 content_profile.py "$dump" --out ../out >/dev/null) || { echo "prepare failed" >&2; exit 1; }
# GR2_ISA_REWRITE (or TLG_ISA_REWRITE)=1 or a list of sets (e.g. sse4a): rewrite those instructions
# even on a CPU that has them, to test the emulation (needs iced-x86; ISA_PYTHON picks the Python
# that has it). On a CPU that lacks one (SSE4A on every Intel CPU) the table is always built.
isa=(); isa_policy=${GR2_ISA_REWRITE:-${TLG_ISA_REWRITE:-}}
rm -f "$port/out/isa-rewrite.bin"
if [[ $isa_policy != 0 ]] && { [[ -n $isa_policy ]] || "$port/out/tlg-probe" --cpu-features | grep -q '^CPU: missing'; }; then
    (cd "$port/scripts" && "${ISA_PYTHON:-python3}" isa_rewrite.py ../out/boot-linked.bin --out ../out) &&
        isa=(--isa-rewrite "$port/out/isa-rewrite.bin") || { echo "isa_rewrite.py failed" >&2; exit 1; }
fi
mkdir -p "$port/user" "$port/out/logs"
log=$port/out/logs/gr2-$(date +%Y%m%d-%H%M%S).log
ln -sfn "$log" "$port/out/last_run.log"
export TLG_PIPELINE_BINARIES=0 TLG_READBACKS=2 TLG_GC_BUDGET_MB=5600 TLG_UPSCALER=off TLG_JITTER=0 \
       TLG_OBJECT_MOTION=0 TLG_FRAME_STATS=1 TLG_NGS2=native TLG_LANGUAGE=${TLG_LANGUAGE:-1}
pad=$port/out/pad_input.txt; : > "$pad"; export TLG_PAD_FILE=$pad
if [[ -n $shots ]]; then
    mkdir -p "$shots"; export TLG_FRAME_DUMP_TRIGGER=$shots/trigger TLG_DUMP_DIR=$shots
fi
(cd "$port/user" && exec "$port/out/tlg-probe" "$port/out/boot-linked.bin" --app0 "$dump" --user . \
    --content-profile "$port/out/content.bin" "${isa[@]}" --timeout "$seconds") > "$log" 2>&1 &
game=$!
start=$(date +%s)
if [[ -n $script && -f $script ]]; then
    while read -r at buttons; do
        [[ -z $at || $at == \#* ]] && continue
        while (( $(date +%s) - start < at )); do sleep 0.2; done
        kill -0 "$game" 2>/dev/null || break
        if [[ $buttons == shot ]]; then [[ -n $shots ]] && touch "$shots/trigger"; continue; fi
        echo "$buttons" > "$pad"; sleep 0.3; : > "$pad"
        echo "[$(( $(date +%s) - start ))s] $buttons"
    done < "$script"
fi
wait "$game"; code=$?
if [[ -n $shots ]]; then
    python3 - "$shots" <<'EOF'
import sys, re
from pathlib import Path
from PIL import Image
for raw in Path(sys.argv[1]).glob('display_*.raw'):
    m = re.search(r'_(\d+)x(\d+)\.raw$', raw.name); w, h = int(m[1]), int(m[2])
    d = raw.read_bytes()
    if len(d) >= w * h * 4:
        Image.frombytes('RGBA', (w, h), d[:w*h*4]).convert('RGB').save(raw.with_suffix('.png'))
EOF
fi
echo "exit $code; log: $log"
