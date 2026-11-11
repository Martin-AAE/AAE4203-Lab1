#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_all.sh -- reproduce the whole Section 6 / Section 7.1 conversion chain
#
#   UBX  --(RTKLIB convbin = RTKCONV engine)-->  RINEX .obs/.nav
#   RINEX --(tools/rinex2csv.py = rinex2csv.m equivalent)-->  CSV tables
#
# Usage:  ./run_all.sh          (from this directory)
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p work csv kml submission

CONVBIN="${CONVBIN:-tools/bin/convbin}"
RNX2RTKP="${RNX2RTKP:-tools/bin/rnx2rtkp}"
POS2KML="${POS2KML:-tools/bin/pos2kml}"
PY="${PY:-python3}"

echo "== 0. checks ==========================================================="
[ -x "$CONVBIN" ] || { echo "missing $CONVBIN"; exit 1; }
$PY -c "import sys; print('python', sys.version.split()[0])"

echo
echo "== 1. UBX -> RINEX (RTKCONV equivalent) ================================"
# -r ubx     : u-blox format (RTKCONV "Format: u-blox")
# -o/-n      : .obs and .nav outputs (RTKCONV "RINEX OBS" / "RINEX NAV" ticks)
# -od -os    : Doppler and C/N0 in the observation file (needed for the masks)
# -oi -ot -ol: ionospheric / UTC / leap-second records in the navigation header
# -v 3.04    : RINEX version (RTKLIB 2.5 default)
for f in Move static; do
  echo "-- $f.ubx"
  "$CONVBIN" -r ubx -od -os -oi -ot -ol -v 3.04 \
             -d rinex -o "$f.obs" -n "$f.nav" "input/$f.ubx" \
             > "work/convbin_$f.log" 2>&1 || { echo "convbin failed"; exit 1; }
done
ls -l rinex/

echo
echo "== 2. RINEX -> CSV (rinex2csv.m equivalent) ============================"
# GPS L1 only, 15 deg elevation mask, 15 dB-Hz C/N0 mask  (as rinex2csv.m)
"$PY" tools/rinex2csv.py --obs rinex/Move.obs   --nav rinex/Move.nav \
      --out csv/Move   --systems G --elev-mask 15 --cn0-mask 15

# the static log contains no GPS ionospheric coefficients (no GPS subframe 4
# page 18 was decoded in that session); take them from the Move log of the
# same day and the same site -- they are valid for the whole constellation
"$PY" tools/rinex2csv.py --obs rinex/static.obs --nav rinex/static.nav \
      --iono-from rinex/Move.nav \
      --out csv/static --systems G --elev-mask 15 --cn0-mask 15

echo
echo "== 3. multi-GNSS variant (for the improvements of Section 8.2) ========="
"$PY" tools/rinex2csv.py --obs rinex/Move.obs   --nav rinex/Move.nav \
      --out csv/Move_multi   --systems GREC
"$PY" tools/rinex2csv.py --obs rinex/static.obs --nav rinex/static.nav \
      --iono-from rinex/Move.nav \
      --out csv/static_multi --systems GREC

echo
echo "== 4. validation: independent SPP from the CSV files ==================="
if [ -x "$RNX2RTKP" ]; then
  mkdir -p work/spp work/check
  "$RNX2RTKP" -k config/spp.conf -o work/spp/Move_spp.pos   rinex/Move.obs   rinex/Move.nav   >/dev/null 2>&1 || true
  "$RNX2RTKP" -k config/spp.conf -o work/spp/static_spp.pos rinex/static.obs rinex/static.nav >/dev/null 2>&1 || true
  "$RNX2RTKP" -k config/spp_multi.conf -o work/spp/Move_rtk_multi.pos   rinex/Move.obs   rinex/Move.nav   >/dev/null 2>&1 || true
  "$RNX2RTKP" -k config/spp_multi.conf -o work/spp/static_rtk_multi.pos rinex/static.obs rinex/static.nav >/dev/null 2>&1 || true
  for p in "csv/Move work/spp/Move_spp.pos" "csv/static work/spp/static_spp.pos" \
           "csv/Move_multi work/spp/Move_rtk_multi.pos" \
           "csv/static_multi work/spp/static_rtk_multi.pos"; do
    set -- $p
    echo "--- $1 (reference: $(basename "$2"))"
    "$PY" tools/csv_spp_check.py --csv "$1" --ref "$2" \
          --out "work/check/$(basename "$1")_csvspp.pos" | tail -9
  done
else
  echo "(rnx2rtkp not available -- skipping the comparison)"
fi

echo
echo "== 5. receiver solution + KML (Google Earth) ==========================="
# receiver's own solution (UBX-NAV-HPPOSECEF), Lab tutorial 7.2
"$PY" tools/ubx_hpposecef.py --ubx input/Move.ubx --obs rinex/Move.obs \
      --out csv/Move_receiver --pos work/spp/Move_receiver.pos
"$PY" tools/ubx_hpposecef.py --ubx input/static.ubx --obs rinex/static.obs \
      --out csv/static_receiver --pos work/spp/static_receiver.pos

# single tracks: RTKPLOT "Tools -> Convert to KML" (pos2kml)
mkdir -p kml
if [ -x "$POS2KML" ]; then
  "$POS2KML" -o kml/Move_rtklib_gps.kml      work/spp/Move_spp.pos
  "$POS2KML" -o kml/Move_rtklib_multi.kml    work/spp/Move_rtk_multi.pos
  "$POS2KML" -c 2 -o kml/Move_receiver.kml   work/spp/Move_receiver.pos
  "$POS2KML" -o kml/static_rtklib.kml        work/spp/static_spp.pos
  "$POS2KML" -c 2 -o kml/static_receiver.kml work/spp/static_receiver.pos
fi

# several solutions in one KML (Fig. 27 style)
"$PY" tools/make_kml.py --out kml/Move_compare.kml \
      --name "Move 2026-10-30 08:07-08:23 GPST" \
      --track work/spp/Move_spp.pos          "RTKLIB SPP (GPS)" yellow \
      --track work/spp/Move_rtk_multi.pos    "RTKLIB SPP (GPS+GLO+GAL+BDS)" orange \
      --track work/spp/Move_receiver.pos     "Receiver NAV-HPPOSECEF" green
"$PY" tools/make_kml.py --out kml/Move_compare_clean.kml --max-offset 50 \
      --name "Move 2026-10-30 08:07-08:23 GPST (outliers removed)" \
      --track work/spp/Move_spp.pos          "RTKLIB SPP (GPS)" yellow \
      --track work/spp/Move_rtk_multi.pos    "RTKLIB SPP (GPS+GLO+GAL+BDS)" orange \
      --track work/spp/Move_receiver.pos     "Receiver NAV-HPPOSECEF" green
"$PY" tools/make_kml.py --out kml/static_compare.kml \
      --name "static 2026-10-30 08:24-08:28 GPST" \
      --track work/spp/static_spp.pos        "RTKLIB SPP (GPS)" yellow \
      --track work/spp/static_rtk_multi.pos  "RTKLIB SPP (GPS+GLO+GAL+BDS)" orange \
      --track work/spp/static_receiver.pos   "Receiver NAV-HPPOSECEF" green

# the solution built from the CSV files, for comparison with RTKLIB
if [ -f work/check/Move_csvspp.pos ] && [ -f work/check/Move_multi_csvspp.pos ]; then
  "$PY" tools/make_kml.py --out kml/Move_csv_pipeline.kml \
        --name "SPP computed from the rinex2csv CSV files" \
        --track work/check/Move_csvspp.pos       "CSV chain SPP (GPS)"       cyan \
        --track work/check/Move_multi_csvspp.pos "CSV chain SPP (multi-GNSS)" blue
fi

echo
echo "== done ================================================================"
find csv rinex -name '*.csv' -o -name '*.obs' -o -name '*.nav' | sort
