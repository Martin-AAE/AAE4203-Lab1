AAE4203 accuracy challenge — submission files
=============================================

Format (Lab tutorial, Section 9.1 / Table 14): exactly five columns and a header
line, one row per epoch in time order, ECEF metres with three decimals.

    gps_week,gps_tow_s,x_ecef_m,y_ecef_m,z_ecef_m
    2442,461257.005,-2418193.562,5385774.936,2405751.455
    ...

File names: GXX_benchmark.csv (benchmark dataset, scored) and
GXX_owndata.csv (own field data, format checked), XX = two-digit group number.

Contents of this folder
-----------------------
G04_owndata.csv   945 epochs of the kinematic session (2026-10-30
                  08:07:37 - 08:23:30 GPST), computed with the best estimator
                  v4: GPS + Galileo + BeiDou, one clock per constellation,
                  elevation weights and residual-based rejection, followed by
                  the same 40 m/s physical screen (9 epochs removed).

G04_benchmark.csv   1491 epochs of the UrbanNav deep1 benchmark
                  (2021-05-21 06:29:06 - 06:54:39 GPST, week 2158), computed
                  with the same v4 estimator on the benchmark RINEX files:
                  GPS + GLONASS + Galileo + BeiDou (18.6 satellites per epoch),
                  elevation weights, residual-based rejection (4 sigma, prior
                  noise 4 m), followed by a physical speed screen that removes
                  epochs implying more than 40 m/s (39 epochs); the remaining
                  epochs are 1 Hz and follow the route through Tsim Sha Tsui.

Where the benchmark came from
-----------------------------
  https://github.com/weisongwen/AAE4203-S12627  (folder Lab1/benchmark)
  benchmark/urbannav_deep1.obs   RINEX 3.03, 1534 epochs, 2021-05-21
  benchmark/urbannav_deep1.nav   broadcast navigation, normalised to RINEX 3.04
                                 with convbin (the original file glues negative
                                 numbers to the previous field)

Pipeline used for the benchmark (reproducible):
  tools/bin/convbin -r rinex -v 3.04 -oi -ot -ol -d work/bench_norm -n bench.nav \
        benchmark/urbannav_deep1.nav
  tools/bin/rnx2rtkp -k work/spp_multi.conf -o work/spp/bench_rtk.pos \
        benchmark/urbannav_deep1.obs work/bench_norm/bench.nav     # apriori + check
  python3 tools/rinex2csv.py --obs benchmark/urbannav_deep1.obs \
        --nav work/bench_norm/bench.nav --apriori-pos work/spp/bench_rtk.pos \
        --out csv/benchmark_grec --systems GREC
  python3 tools/spp_versions.py --csv csv/benchmark_grec \
        --out work/spp_ablation/bench/benchmark_grec --versions v4 \
        --systems GREC --ref work/spp/bench_rtk.pos
  python3 tools/make_submission.py --pos work/spp_ablation/bench/benchmark_grec_v4.pos \
        --group 04 --kind benchmark --max-speed 40

Cross-check: against the RTKLIB single-point solution of the same files the
2-D difference is 4.3 m (median), 28.8 m (95th percentile).

Change the group number with --group (e.g. --group 12 -> G12_*.csv); the
default 04 follows the group number used in the report.

Validation
----------
    python3 tools/make_submission.py --check submission/G04_benchmark.csv

checks the header, the five columns, GPS week / TOW ranges, that every point is
on the Earth (6200-6600 km from the geocentre), that the epochs are strictly
increasing and that the coordinates carry at most three decimals.
