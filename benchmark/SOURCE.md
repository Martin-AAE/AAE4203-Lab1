# Benchmark data (UrbanNav deep1)

Taken from the course repository
<https://github.com/weisongwen/AAE4203-S12627>, folder `Lab1/benchmark`
(commit of 2026-10-30).

| file | content |
|---|---|
| `urbannav_deep1.obs` | RINEX 3.03 observations, GPS week 2158, 2021-05-21 06:29:06 – 06:54:39 GPST, 1534 epochs at 1 Hz, GPS/GLONASS/Galileo/QZSS/SBAS/BeiDou |
| `urbannav_deep1.nav` | broadcast navigation, multi-constellation, same day |

Two properties of the files matter for the pipeline:

1. the navigation file is written without field separators between negative
   values, so it is normalised first with
   `tools/bin/convbin -r rinex -v 3.04 -oi -ot -ol`;
2. the observation header carries a zero `APPROX POSITION XYZ`, so
   `rinex2csv.py` takes its linearisation point from `--apriori-pos`, an RTKLIB
   single-point solution of the same files.

The reference trajectory used for scoring is not distributed with the data;
the scores are computed by the teaching team.

UrbanNav is released by the ITS Lab of the Hong Kong Polytechnic University
(<https://github.com/IPNL-POLYU/UrbanNavDataset>); cite Hsu et al., ION GNSS+
2021, if the data are reused.
