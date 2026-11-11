# AAE4203 Lab 1 — GNSS positioning (Group 4)

Course repository for the GNSS positioning laboratory of *AAE4203 — Guidance and
Navigation* (PolyU).  It contains the raw field data, the documented Python
scripts, the processing chain and the two submission files of the accuracy
challenge.

**What the repository shows**

1. UBX → RINEX 3.04 conversion of two u-blox logs (`input/*.ubx`) with the
   RTKCONV engine (`convbin`, RTKLIB 2.5.0);
2. RINEX → CSV conversion with a Python re-implementation of `rinex2csv.m`
   (broadcast ephemeris, Klobuchar, Saastamoinen);
3. a weighted least-squares SPP with one receiver clock per constellation,
   elevation weighting and residual-based outlier rejection (versions v1–v4);
4. validation against the RTKPOST solution and the receiver's own
   NAV-HPPOSECEF solution;
5. the UrbanNav deep1 benchmark and the two submission files
   `submission/G04_benchmark.csv` and `submission/G04_owndata.csv`.

**Quick start**

```bash
./run_all.sh          # own data:  UBX -> RINEX -> CSV -> SPP -> KML
./run_benchmark.sh    # benchmark: UrbanNav deep1 -> submission/G04_benchmark.csv
```

Both scripts need only a Python 3 interpreter and the RTKLIB binaries that are
included in `tools/bin/` (macOS arm64 builds of RTKLIB 2.5.0, rtklibexplorer).
The Python scripts themselves use the standard library only; `requirements.txt`
lists the two optional packages needed to rebuild the figures and the report.

**Repository layout**

```text
AAE4203-Lab/
├── input/            raw u-blox logs (Move.ubx, static.ubx)
├── benchmark/        UrbanNav deep1 RINEX + SOURCE.md (provenance)
├── rinex/            RINEX 3.04 produced by convbin
├── config/           RTKLIB processing options (rnx2rtkp)
├── tools/            documented Python scripts + RTKLIB binaries
├── submission/       G04_benchmark.csv, G04_owndata.csv, README.txt
├── results/          ablation summary and per-epoch solutions
├── report/           report sources (build_report.py, make_figures.py) and PDF
├── run_all.sh        own-data pipeline
├── run_benchmark.sh  benchmark pipeline
└── README.md         this file (details below)
```

**Data**

* `input/Move.ubx`, `input/static.ubx` — field logs of 2026-10-30
  (954 and 271 epochs at 1 Hz, GPS week 2442).
* `benchmark/urbannav_deep1.{obs,nav}` — UrbanNav deep1, 2021-05-21, from the
  course repository; see `benchmark/SOURCE.md`.

**Submission files**

| file | content |
|---|---|
| `submission/G04_benchmark.csv` | 1491 epochs of the UrbanNav deep1 benchmark |
| `submission/G04_owndata.csv` | 945 epochs of our own kinematic session |

Five columns (`gps_week,gps_tow_s,x_ecef_m,y_ecef_m,z_ecef_m`), one row per
epoch, ECEF metres with three decimals, as required by the tutorial §9.1.
`python3 tools/make_submission.py --check submission/G04_benchmark.csv`
validates the format.

---

The sections below document the conversion chain in detail.

# Lab 6 — UBX → RINEX → CSV (Lab tutorial Section 6 and Section 7.1)

Conversion of the two u-blox logs `Move.ubx` and `static.ubx` into

1. **RINEX** observation + navigation files with **RTKCONV** (Section 6.1), and
2. the **CSV input tables** of the SPP exercise with the equivalent of
   `rinex2csv.m` (Section 7.1): `pseudoranges_meas.csv`,
   `satellite_positions.csv`, `satellite_clock_bias.csv`,
   `ionospheric_delay.csv`, `tropospheric_delay.csv`, `epochs.csv` and a
   conversion summary.

Everything is reproducible with `./run_all.sh`.

---

## 1. What the tutorial asks for

> **6.1 Conversion to RINEX with RTKCONV** — "In RTKCONV select the `.ubx` file,
> set the format to u-blox, tick the `.obs` and `.nav` outputs, and click
> Convert (Fig. 15)."

> **7.1 RINEX to CSV with rinex2csv.m** — "The MATLAB function
> `rinex2csv(obs_file, nav_file, out_dir)` … reads the RINEX files with
> MatRTKLIB, computes satellite positions and clock offsets from the broadcast
> ephemeris, evaluates the ionospheric and tropospheric models, and writes one
> CSV file per quantity to `out_dir`: `pseudoranges_meas.csv`,
> `satellite_clock_bias.csv`, `satellite_positions.csv`,
> `ionospheric_delay.csv` and `tropospheric_delay.csv`, together with
> `epochs.csv` and a conversion summary … it uses GPS L1 with a 15° elevation
> mask and a 15 dB-Hz C/N₀ mask."

## 2. Tool used instead of the RTKCONV GUI

RTKCONV is the **Windows GUI** layer of RTKLIB; the conversion itself is done by
`convrnx.c`, which the console tool **`convbin`** drives with exactly the same
options. On macOS the GUI (Borland/Qt builds) is not available, so this project
uses `convbin` from the **same release, RTKLIB 2.5.0 (rtklibexplorer)**, which
is the version named in the tutorial.

The mapping of the RTKCONV settings (Fig. 15) to `convbin` options is:

| RTKCONV (GUI)                    | `convbin` option |
|----------------------------------|------------------|
| Input file `.ubx`                | positional argument |
| Format = **u-blox**              | `-r ubx` |
| ☑ RINEX **OBS** output           | `-o <file>.obs` |
| ☑ RINEX **NAV** output           | `-n <file>.nav` |
| ☑ Doppler / ☑ SNR in obs         | `-od -os` |
| Iono / UTC / leap in nav header  | `-oi -ot -ol` |
| RINEX version 3.04 (default)     | `-v 3.04` |

`convbin`/`rnx2rtkp` were compiled from the v2.5.0 tag
(`https://github.com/rtklibexplorer/RTKLIB`) with clang; the binaries are kept in
`tools/bin/` so the pipeline does not depend on a system-wide RTKLIB.

## 3. Commands

```bash
# 1) UBX -> RINEX  (RTKCONV equivalent)
tools/bin/convbin -r ubx -od -os -oi -ot -ol -v 3.04 \
                  -d rinex -o Move.obs -n Move.nav input/Move.ubx
tools/bin/convbin -r ubx -od -os -oi -ot -ol -v 3.04 \
                  -d rinex -o static.obs -n static.nav input/static.ubx

# 2) RINEX -> CSV  (rinex2csv.m equivalent, GPS L1, 15 deg, 15 dB-Hz)
python3 tools/rinex2csv.py --obs rinex/Move.obs --nav rinex/Move.nav \
        --out csv/Move --systems G --elev-mask 15 --cn0-mask 15

python3 tools/rinex2csv.py --obs rinex/static.obs --nav rinex/static.nav \
        --iono-from rinex/Move.nav \
        --out csv/static --systems G --elev-mask 15 --cn0-mask 15

# 3) multi-GNSS variant (useful for the improvements of Section 8.2)
python3 tools/rinex2csv.py --obs rinex/Move.obs --nav rinex/Move.nav \
        --out csv/Move_multi --systems GREC
```

### Why MATLAB was not used

`rinex2csv.m` needs MATLAB **and** MatRTKLIB (a MEX build of RTKLIB). Neither
MatRTKLIB nor the `Lab1` folder of the course repository is present on this
machine, so the tutorial's alternative — a Python tool — was implemented
instead: `tools/rinex2csv.py` reproduces the described functionality with the
**same numerical models as RTKLIB**, so its output is consistent with
RTKPOST/MatRTKLIB results:

| quantity | model (RTKLIB source) |
|---|---|
| satellite position & clock | broadcast ephemeris, `eph2pos()` / `geph2pos()` |
| signal transmission time | `satposs()` two-step clock iteration |
| ionosphere | Klobuchar, GPS α/β from the nav header (`ionmodel()`) |
| troposphere | Saastamoinen, standard atmosphere, RH 70 % (`tropmodel()`) |
| earth rotation | first-order Sagnac term of `geodist()` |

`rinex2csv.py` supports RINEX 3.x observation and navigation files; RINEX 2.x is
rejected with a clear message (the files here are 3.04).

## 4. Results

### 4.1 RINEX (`rinex/`)

| file | content | epochs | period (GPST) |
|------|---------|--------|----------------|
| `Move.obs` | 3.1 MB, mixed G/R/E/C, 8 obs per system | **954** (1 Hz) | 2026‑10‑30 08:07:37.005 – 08:23:30.006 |
| `Move.nav` | 41 records: 6 GPS, 8 GLONASS, 17 Galileo, 10 BDS | — | — |
| `static.obs` | 1.1 MB, mixed G/R/E/C | **271** (1 Hz) | 2026‑10‑30 08:24:02.006 – 08:28:32.006 |
| `static.nav` | 29 records: 6 GPS, 8 GLONASS, 8 Galileo, 7 BDS | — | — |

Observation types per system: `C1C L1C D1C S1C C2X L2X D2X S2X` (GPS),
`C1C … C2C …` (GLONASS), `C1X … C7X …` (Galileo), `C2I … C7I …` (BDS).
The navigation header also carries `IONOSPHERIC CORR` (GPSA/GPSB),
`TIME SYSTEM CORR` and `LEAP SECONDS` (18 s).

### 4.2 CSV (`csv/`)

Each directory contains the seven tables plus `conversion_summary.txt/.json`:

| directory | systems | rows in `pseudoranges_meas.csv` | sats/epoch |
|-----------|---------|------------------------------|------------|
| `csv/Move` | GPS (as `rinex2csv.m`) | 4 818 (954 epochs) | 5.05 |
| `csv/Move_multi` | GPS+GLO+GAL+BDS | 19 946 | 20.91 |
| `csv/static` | GPS | 1 488 (271 epochs) | 5.49 |
| `csv/static_multi` | GPS+GLO+GAL+BDS | 6 286 | 23.20 |

All tables are long-format and share the key
`epoch_id, gps_week, gps_tow_s, utc_time_iso, sys, prn, sat_id`, so the five
quantity files can be joined row-by-row (identical row order).

**Column dictionary**

`epochs.csv`
`epoch_id, gps_week, gps_tow_s, utc_time_iso, n_sat_visible, n_sat_used, rx_x_ecef_m, rx_y_ecef_m, rx_z_ecef_m`
(the receiver column is the `APPROX POSITION XYZ` of the RINEX header — the
linearisation point for the SPP).

`pseudoranges_meas.csv`
`… sat_id, obs_code, pseudorange_m, cn0_dbhz, elevation_deg, azimuth_deg`
— raw pseudorange of the L1/E1/B1 signal, already **after** both masks.

`satellite_positions.csv`
`… sat_id, x_ecef_m, y_ecef_m, z_ecef_m, elevation_deg, azimuth_deg, geometric_range_m, sagnac_correction_m, signal_travel_time_s`
— satellite position at signal transmission time in ECEF.

`satellite_clock_bias.csv`
`… sat_id, sv_clock_bias_s, sv_relativity_s, sv_clock_correction_m, tgd_m, sv_clock_correction_tgd_m`

`ionospheric_delay.csv`
`… sat_id, iono_slant_m, iono_vertical_m, iono_mapping_factor`

`tropospheric_delay.csv`
`… sat_id, tropo_dry_m, tropo_wet_m, tropo_slant_m`

`satellite_visibility.csv`
`… obs_code, pseudorange_m, cn0_dbhz, elevation_deg, azimuth_deg, elev_mask_pass, cn0_mask_pass, used`
— **all** tracked signals before the masks (for the C/N₀, satellite-count and
sky-plot analysis of Figs. 28–30).

**Pseudorange model used downstream**

```
P_corr = P_meas + sv_clock_correction_tgd_m − iono_slant_m − tropo_slant_m
       = ρ(sat, rx) + c·dt_rx
```
where `sv_clock_correction_tgd_m = c·(sv_clock_bias_s + sv_relativity_s) − tgd_m`.

Sanity values in `csv/Move_multi`: ionospheric slant delay 6.0–15.2 m
(≈ 6 m vertical), tropospheric slant delay 2.4–9.1 m, C/N₀ 15–52 dB-Hz.

### 4.3 Why `static` uses the ionospheric coefficients of `Move`

The `static` log contains no GPS subframe 4 page 18 (no `GPSA`/`GPSB` in
`static.nav`), so the GPS Klobuchar coefficients are missing. They are identical
for the whole constellation and valid for about one day, so they are taken from
the `Move` log recorded a few minutes earlier at the same site
(`--iono-from rinex/Move.nav`). Without them the ionospheric delay would have to
be set to zero (~5–15 m of pseudorange error).

## 5. Validation

The CSV files were checked end-to-end: `tools/csv_spp_check.py` reads the five
quantity CSVs, solves a plain weighted least-squares SPP per epoch (one receiver
clock per constellation, weight sin²el) and compares the trajectory with the
RTKLIB/RTKPOST single solution (`rnx2rtkp -m 1`, `work/spp/*.pos`).

| dataset | epochs solved | sat/epoch | E bias | N bias | 3D RMS | 2D 95 % |
|---|---|---|---|---|---|---|
| `csv/Move` | 918 / 954 | 5.1 | −0.42 m | −0.34 m | 11.4 m | 4.9 m |
| `csv/static` | 271 | 5.5 | −0.73 m | −1.51 m | 13.3 m | 4.9 m |
| `csv/Move_multi` | 954 | 20.9 | −0.17 m | +0.02 m | 21.8 m | 5.3 m |
| `csv/static_multi` | 271 | 23.2 | +0.72 m | −0.90 m | 12.6 m | 2.6 m |

The sub-metre horizontal biases show that the satellite orbits, clock offsets,
ionosphere and troposphere in the CSVs are consistent with RTKLIB; the remaining
scatter comes from the different weighting (sin²el here, SNR-based in RTKLIB)
and from multipath in the urban environment. The complete output of the check is
in `work/check/validation_report.txt`.

## 6. Google Earth: KML

The tutorial converts the solution with **RTKPOST → Tools → Convert to KML**
(Fig. 25) and imports it into Google Earth (Figs. 26–27). In the console this is
RTKLIB's **`pos2kml`**, which converts any `.pos` file to KML:

```bash
# one track (the RTKPLOT / RTKPOST "Convert to KML" equivalent)
tools/bin/pos2kml -o kml/Move_rtklib_gps.kml work/spp/Move_spp.pos
#   -c : track colour (1 white, 2 green, 3 orange, 4 red, 5 yellow [default])
#   -a : absolute altitude instead of clamp-to-ground
#   -i : thin the track to one point every N seconds
#   -gpx : GPX instead of KML

# several solutions in one file, one colour each (Fig. 27 style)
python3 tools/make_kml.py --out kml/Move_compare.kml \
    --track work/spp/Move_spp.pos       "RTKLIB SPP (GPS)" yellow \
    --track work/spp/Move_rtk_multi.pos "RTKLIB SPP (G/R/E/C)" orange \
    --track work/spp/Move_receiver.pos  "Receiver NAV-HPPOSECEF" green
```

The green track is the **receiver's own solution**, taken from
`UBX-NAV-HPPOSECEF` (Section 7.2) with `tools/ubx_hpposecef.py`, which writes
`csv/Move_receiver/NAV-HPPOSECEF.csv` (iTOW in ms of week, ECEF in cm + 0.1 mm
high-precision part) and a `.pos` file for `pos2kml`.

| file | content |
|---|---|
| `kml/Move_rtklib_gps.kml` | RTKLIB SPP, GPS only (yellow) |
| `kml/Move_rtklib_multi.kml` | RTKLIB SPP, GPS+GLO+GAL+BDS (yellow) |
| `kml/Move_receiver.kml` | receiver NAV-HPPOSECEF (green) |
| `kml/Move_compare.kml` | all three tracks in one document, one folder each |
| `kml/Move_compare_clean.kml` | same, epochs more than 50 m from the median removed (9 of 919) |
| `kml/Move_csv_pipeline.kml` | SPP recomputed from the CSV files (cyan/blue) — checks the chain |
| `kml/static_*.kml` | same for the static dataset (15 m filter) |

**Opening them.** Google Earth Pro on the Mac: *File → Open…* → choose the
`.kml`; or drag the file onto the globe. Google Earth Web
(earth.google.com): *Projects → New project → Import KML file from computer*.
All tracks are `clampToGround` by default, so they lie on the terrain; the
folders in `*_compare.kml` can be switched on and off in the *Places* panel.

What to expect: the walk covers about **85 × 85 m** around 22.3055° N,
114.1800° E (the static antenna is a cluster of ~1 m). The RTKLIB single-point
solutions scatter by 20–40 m (2D 95 %) in the canyon, while the receiver's own
solution is smoother — the same contrast as Fig. 27. The few isolated spikes
(e.g. 430 m at one epoch) come from epochs with a poor satellite geometry; the
`_clean` files remove them for readability.

## 7. Observations on the data

* **Sparse GPS ephemerides.** Only **6 GPS satellites** have a decoded broadcast
  ephemeris in `Move.nav` (G04, G08, G09, G16, G27, G31). G02, G03, G26 and G28
  are tracked for hundreds of epochs but were never fully decoded (the receiver
  shares its channels between four constellations), so the GPS-only solution has
  only 5–6 satellites per epoch. The multi-GNSS variant reaches 21–23 satellites
  and a much more stable geometry — this is exactly the "multi-constellation"
  improvement of Section 8.2.
* **Second-frequency-only signals.** About 8 % of the records carry only
  `C2X`/`C2C`/`C7X`/`C7I` (no L1/B1 pseudorange, e.g. when the L1 signal was not
  tracked). They are correctly counted as *no L1 pseudorange* and dropped by the
  single-frequency conversion; a dual-frequency solution would use them.
* **`Move` header height.** The `APPROX POSITION XYZ` of `Move.obs` has an
  ellipsoidal height of about 250 m, i.e. the receiver's single-epoch estimate is
  poor in the canyon. It is only used as a linearisation point; RTKLIB's SPP of
  the same file settles at ≈ 22 m.
* **Time systems.** All epochs are GPST; `utc_time_iso` in the CSVs is GPST
  − 18 s (leap seconds read from the RINEX header). GLONASS navigation epochs are
  UTC and are converted to GPST; BDS epochs are BDT and are converted with
  +1356 weeks and +14 s.

## 8. Files

```
AAE4203-Lab/
├── input/            Move.ubx, static.ubx, tutorial PDF
├── rinex/            Move.obs, Move.nav, static.obs, static.nav
├── csv/
│   ├── Move/         GPS L1, 15 deg / 15 dB-Hz   (as rinex2csv.m)
│   ├── Move_multi/   GPS+GLO+GAL+BDS
│   ├── static/       GPS L1
│   └── static_multi/ GPS+GLO+GAL+BDS
├── tools/
│   ├── rinex2csv.py       RINEX -> CSV converter (rinex2csv.m equivalent)
│   ├── csv_spp_check.py   independent SPP from the CSVs + comparison
│   ├── ubx_hpposecef.py   NAV-HPPOSECEF -> CSV/.pos (receiver solution)
│   ├── make_kml.py        multi-track KML for Google Earth
│   ├── spp_versions.py    SPP v1..v4 ablation (multi-GNSS, weights, FDE)
│   ├── make_submission.py GXX_owndata.csv / GXX_benchmark.csv writer + checker
│   └── plot_ablation.py   figure of the ablation
│   ├── bin/convbin        RTKLIB 2.5.0 (RTKCONV engine)
│   ├── bin/rnx2rtkp       RTKLIB 2.5.0 (RTKPOST engine, used for the check)
│   └── bin/pos2kml        RTKLIB 2.5.0 (RTKPLOT "Convert to KML")
│   ├── Move_receiver/   NAV-HPPOSECEF.csv (receiver's own solution, 7.2)
│   └── static_receiver/
├── kml/              Google Earth tracks (see section 6)
├── benchmark/        UrbanNav deep1 benchmark RINEX (from the course repo)
├── submission/       GXX_benchmark.csv and GXX_owndata.csv
├── report/           lab report (DOCX + PDF), build script, figures
├── work/             logs, RTKLIB .pos/.stat outputs, validation report
├── run_all.sh        full reproducible pipeline
└── README.md
```

## 9. Reproducibility notes

* RTKLIB v2.5.0 needs two small clang fixes on recent macOS toolchains: the
  sources rely on implicit `#include <stdio.h>` and the `rnx2rtkp` makefile links
  `-lgfortran`. Both were handled by compiling with
  `CC="clang -include stdio.h -include string.h -include stdlib.h -include math.h -include ctype.h"`
  and by replacing `LDLIBS = -lgfortran -lm` with `-lm`.
* `python3 tools/spp_versions.py --all` runs the four estimator versions
  (GPS-only baseline, multi-GNSS with one clock per system, elevation
  weighting, residual-based rejection) and writes `work/spp_ablation/`;
  `--selftest` injects a 50 m bias and checks that the FDE loop removes it.
* `run_all.sh` regenerates the RINEX files, the four CSV sets and the validation
  report; it takes a few seconds per dataset.
* `report/build_report.py` rebuilds the Word report from the numbers in
  `work/report_stats.txt` and `work/report_validation.txt`; the PDF is exported
  from the DOCX with LibreOffice (`libreoffice-kit convert`).
* the benchmark (UrbanNav deep1) comes from
  https://github.com/weisongwen/AAE4203-S12627 (Lab1/benchmark); its navigation
  file needs `convbin -r rinex` to be normalised before it can be read, and the
  observation header has no approximate position, so `rinex2csv.py` takes the
  apriori from `--apriori-pos` (an RTKLIB SPP of the same data).
* `report/make_figures.py` generates the four report figures into `report/figs/`
  — site map (OpenStreetMap tiles + own trajectory), C/N₀ time series, sky plot
  and the static East–North scatter.  It needs matplotlib:
  `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 report/make_figures.py`
  (the bundled runtime cannot load matplotlib's binary extensions).
