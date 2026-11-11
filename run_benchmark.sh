#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_benchmark.sh -- reproduce the accuracy-challenge submission file
#                     G04_benchmark.csv from the UrbanNav deep1 benchmark.
#
#   benchmark/urbannav_deep1.obs/.nav   (RINEX 3.03, 1534 epochs, 2021-05-21)
#        | convbin -r rinex              normalise the navigation file
#        | rnx2rtkp                      RTKLIB SPP -> apriori + cross-check
#        | rinex2csv.py                  RINEX -> CSV tables (GREC)
#        | spp_versions.py v4            WLS SPP, one clock per system, FDE
#        | make_submission.py            five-column submission file
#        v
#   submission/G04_benchmark.csv        (1491 epochs, 40 m/s screen applied)
#
# The benchmark comes from https://github.com/weisongwen/AAE4203-S12627
# (folder Lab1/benchmark).  Its navigation file is written without field
# separators between negative values, and its observation header has a zero
# APPROX POSITION, hence the two preparation steps below.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

CONVBIN="${CONVBIN:-tools/bin/convbin}"
RNX2RTKP="${RNX2RTKP:-tools/bin/rnx2rtkp}"
PY="${PY:-python3}"

mkdir -p work/bench_norm work/spp work/spp_ablation/bench csv/benchmark_grec submission

echo "== 1. normalise the navigation file ===================================="
"$CONVBIN" -r rinex -v 3.04 -oi -ot -ol -d work/bench_norm -n bench.nav \
           benchmark/urbannav_deep1.nav > work/bench_norm/convbin.log 2>&1

echo "== 2. RTKLIB single-point solution (apriori + cross-check) ============="
"$RNX2RTKP" -k config/spp_multi.conf -o work/spp/bench_rtk.pos \
            benchmark/urbannav_deep1.obs work/bench_norm/bench.nav \
            > work/bench_rtk.log 2>&1

echo "== 3. RINEX -> CSV tables (GPS + GLO + GAL + BDS) ====================="
"$PY" tools/rinex2csv.py --obs benchmark/urbannav_deep1.obs \
      --nav work/bench_norm/bench.nav --apriori-pos work/spp/bench_rtk.pos \
      --out csv/benchmark_grec --systems GREC --quiet

echo "== 4. SPP v4 (multi-GNSS, elevation weights, FDE) ====================="
"$PY" tools/spp_versions.py --csv csv/benchmark_grec \
      --out work/spp_ablation/bench/benchmark_grec --versions v4 \
      --systems GREC --ref work/spp/bench_rtk.pos --sigma 4.0

echo "== 5. submission file (40 m/s physical screen) ========================"
"$PY" tools/make_submission.py \
      --pos work/spp_ablation/bench/benchmark_grec_v4.pos \
      --group 04 --kind benchmark --max-speed 40
"$PY" tools/make_submission.py --check submission/G04_benchmark.csv
