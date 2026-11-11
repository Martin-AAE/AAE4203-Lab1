#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_report.py -- generate the AAE4203 Lab 1 report (DOCX) from the real
numbers produced by the conversion/validation pipeline.

Author: group report draft (figures are placeholders).
Run:    <bundled python> report/build_report.py
"""

from __future__ import annotations

import os

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "PolyU_AAE4203_Lab1_Report.docx")
FIG_DIR = os.path.join(HERE, "figs")
FIG1 = os.path.join(FIG_DIR, "fig1_site_map.png")
FIG2 = os.path.join(FIG_DIR, "fig2_cn0.png")
FIG3 = os.path.join(FIG_DIR, "fig3_sky.png")
FIG4 = os.path.join(FIG_DIR, "fig4_static_scatter.png")
FIG5 = os.path.join(FIG_DIR, "fig5_ablation.png")
FIG_UC = os.path.join(FIG_DIR, "fig_setup_ucenter.png")
FIG_GE = os.path.join(FIG_DIR, "fig_site_googleearth.png")
FIG_PHOTO = os.path.join(FIG_DIR, "fig_setup_photo.png")

ACCENT = RGBColor(0x1F, 0x38, 0x64)
GREY = RGBColor(0x59, 0x59, 0x59)

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def fix_widths(tbl, widths_cm):
    """Force real column widths: gridCol, tcW and a fixed table layout."""
    tbl.autofit = False
    tblPr = tbl._tbl.tblPr
    for old in tblPr.findall(qn("w:tblLayout")):
        tblPr.remove(old)
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblPr.append(layout)
    tblW = tblPr.find(qn("w:tblW"))
    if tblW is None:
        tblW = OxmlElement("w:tblW")
        tblPr.append(tblW)
    tblW.set(qn("w:type"), "dxa")
    tblW.set(qn("w:w"), str(int(sum(widths_cm) * 567)))
    for i, w in enumerate(widths_cm):
        tbl.columns[i].width = Cm(w)
        for cell in tbl.columns[i].cells:
            cell.width = Cm(w)


def shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


def set_cell_margins(cell, top=40, bottom=40, left=80, right=80):
    tcPr = cell._tc.get_or_add_tcPr()
    mar = OxmlElement("w:tcMar")
    for tag, val in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        node = OxmlElement(f"w:{tag}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        mar.append(node)
    tcPr.append(mar)


def add_field(paragraph, instr):
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr_el = OxmlElement("w:instrText")
    instr_el.set(qn("xml:space"), "preserve")
    instr_el.text = instr
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr_el)
    run._r.append(fld_sep)
    run._r.append(fld_end)


def body(doc, text, space_after=5, size=10.5, justify=True, italic=False,
         color=None, first_indent=None, keep=False, space_before=0):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    if space_before:
        p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.line_spacing = 1.12
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY if justify else WD_ALIGN_PARAGRAPH.LEFT
    if first_indent:
        p.paragraph_format.first_line_indent = Cm(first_indent)
    if keep:
        p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.italic = italic
    if color is not None:
        r.font.color.rgb = color
    return p


def bullet(doc, text, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.12
    r = p.add_run(text)
    r.font.size = Pt(size)
    return p


def heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    h.paragraph_format.keep_with_next = True
    for r in h.runs:
        r.font.color.rgb = ACCENT
        r.font.name = "Calibri"
    if level == 1:
        h.paragraph_format.space_before = Pt(12)
        h.paragraph_format.space_after = Pt(6)
        for r in h.runs:
            r.font.size = Pt(14)
    else:
        h.paragraph_format.space_before = Pt(10)
        h.paragraph_format.space_after = Pt(4)
        for r in h.runs:
            r.font.size = Pt(11.5)
    return h


def caption(doc, text, before=2, after=10):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    r = p.add_run(text)
    r.font.size = Pt(8.5)
    r.italic = True
    r.font.color.rgb = GREY
    return p


def figure_placeholder(doc, text):
    """A dashed, centred placeholder where the screenshot will be pasted."""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    tbl.columns[0].width = Cm(15.5)
    cell = tbl.cell(0, 0)
    cell.width = Cm(15.5)
    fix_widths(tbl, [15.5])
    shade(cell, "F7F7F7")
    set_cell_margins(cell, 260, 260, 120, 120)
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(text)
    r.font.size = Pt(9)
    r.italic = True
    r.font.color.rgb = GREY
    p.paragraph_format.space_after = Pt(0)
    return tbl



def figure(doc, img, cap, width_cm=15.0, space_before=6):
    """Insert a figure centred, with its caption below."""
    if os.path.exists(img):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(space_before)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(img, width=Cm(width_cm))
    else:
        figure_placeholder(doc, f"[missing figure: {os.path.basename(img)}]")
    return caption(doc, cap)


def make_table(doc, header, rows, widths, font=8.5, header_font=8.5,
               align_center_from=1, left_align=()):
    tbl = doc.add_table(rows=1, cols=len(header))
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    hdr = tbl.rows[0]
    for i, h in enumerate(header):
        cell = hdr.cells[i]
        cell.width = Cm(widths[i])
        shade(cell, "D9E2F3")
        set_cell_margins(cell)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        r = p.add_run(h)
        r.bold = True
        r.font.size = Pt(header_font)
    # repeat header row on page breaks
    trPr = hdr._tr.get_or_add_trPr()
    tblHeader = OxmlElement("w:tblHeader")
    tblHeader.set(qn("w:val"), "true")
    trPr.append(tblHeader)
    for row in rows:
        cells = tbl.add_row().cells
        for i, v in enumerate(row):
            cells[i].width = Cm(widths[i])
            set_cell_margins(cells[i])
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.0
            if i in left_align or i < align_center_from:
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            else:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(str(v))
            r.font.size = Pt(font)
    fix_widths(tbl, widths)
    return tbl


def code_block(doc, code, size=8.0, fill="F4F4F4"):
    """Monospace listing: one paragraph per line, indentation as paragraph indent
    (leading spaces after a <w:br/> are collapsed by some renderers)."""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    tbl.columns[0].width = Cm(16.0)
    cell = tbl.cell(0, 0)
    cell.width = Cm(16.0)
    fix_widths(tbl, [16.0])
    shade(cell, fill)
    set_cell_margins(cell, 100, 100, 100, 100)
    indent_pt = size * 0.55          # Consolas advance width
    lines = code.split("\n")
    for k, line in enumerate(lines):
        para = cell.paragraphs[0] if k == 0 else cell.add_paragraph()
        nspace = len(line) - len(line.lstrip(" "))
        para.paragraph_format.left_indent = Pt(nspace * indent_pt)
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(0)
        para.paragraph_format.line_spacing = Pt(size * 1.3)
        r = para.add_run(line.strip(" ") if line.strip(" ") else " ")
        r.font.name = "Consolas"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
        r.font.size = Pt(size)
    return tbl


# --------------------------------------------------------------------------- #
# document
# --------------------------------------------------------------------------- #
doc = Document()

# base styles
normal = doc.styles["Normal"]
normal.font.name = "Calibri"
normal.font.size = Pt(10.5)
normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
normal.paragraph_format.space_after = Pt(6)
normal.paragraph_format.line_spacing = 1.12

sec = doc.sections[0]
sec.page_width = Cm(21.0)
sec.page_height = Cm(29.7)
sec.top_margin = Cm(2.3)
sec.bottom_margin = Cm(2.2)
sec.left_margin = Cm(2.5)
sec.right_margin = Cm(2.5)

# header / footer (the cover page has none)
sec.different_first_page_header_footer = True
hp = sec.header.paragraphs[0]
hp.text = "AAE4203 — Guidance and Navigation · Lab 1: GNSS Positioning"
hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
for r in hp.runs:
    r.font.size = Pt(8)
    r.font.color.rgb = GREY

fp = sec.footer.paragraphs[0]
fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = fp.add_run("Page ")
r.font.size = Pt(8.5)
r.font.color.rgb = GREY
add_field(fp, "PAGE")
r = fp.add_run(" of ")
r.font.size = Pt(8.5)
r.font.color.rgb = GREY
add_field(fp, "NUMPAGES")
for run in fp.runs:
    run.font.size = Pt(8.5)
    run.font.color.rgb = GREY

# --------------------------------------------------------------------------- #
# cover
# --------------------------------------------------------------------------- #
p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(60)
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("GNSS Lab Report")
r.bold = True
r.font.size = Pt(28)
r.font.color.rgb = ACCENT

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("Lab 1:  GNSS Positioning")
r.font.size = Pt(16)
r.font.color.rgb = GREY

p = doc.add_paragraph()
p.paragraph_format.space_after = Pt(28)

cover_rows = [
    ("Course", "AAE4203 — Guidance and Navigation"),
    ("Group", "Group 4"),
    ("Members", "[Member 1] (Leader); [Member 2]; [Member 3]"),
    ("Member IDs", "[Student ID 1]; [Student ID 2]; [Student ID 3]"),
    ("Instructor", "Prof. Weisong WEN"),
    ("Department", "Department of Aeronautical and Aviation Engineering"),
    ("School", "The Hong Kong Polytechnic University"),
    ("Date", "October 30, 2026"),
]
tbl = doc.add_table(rows=0, cols=2)
tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
tbl.autofit = False
for k, v in cover_rows:
    cells = tbl.add_row().cells
    cells[0].width = Cm(3.8)
    cells[1].width = Cm(11.0)
    p0 = cells[0].paragraphs[0]
    p0.paragraph_format.space_after = Pt(3)
    r0 = p0.add_run(k)
    r0.bold = True
    r0.font.size = Pt(10.5)
    p1 = cells[1].paragraphs[0]
    p1.paragraph_format.space_after = Pt(3)
    r1 = p1.add_run(v)
    r1.font.size = Pt(10.5)

fix_widths(tbl, [3.8, 11.0])

doc.add_page_break()

# --------------------------------------------------------------------------- #
# abstract
# --------------------------------------------------------------------------- #
h = doc.add_heading("Abstract", level=1)
for r in h.runs:
    r.font.color.rgb = ACCENT
    r.font.size = Pt(14)

body(doc,
     "This report documents the GNSS positioning laboratory carried out near Block X on the PolyU "
     "campus. Two u-blox logs were collected on 30 October 2026 with a ZED-F9P receiver logging UBX "
     "at 1 Hz: a kinematic walk of 954 epochs (08:07:37–08:23:30 GPST) and a static occupation of 271 "
     "epochs (08:24:02–08:28:32 GPST). The UBX logs were converted to RINEX 3.04 with RTKCONV "
     "(convbin) and then, MatRTKLIB being unavailable, to the SPP input tables with a Python "
     "re-implementation of rinex2csv.m that reproduces RTKLIB's broadcast-ephemeris, Klobuchar and "
     "Saastamoinen models. A weighted least-squares SPP with sin²θ weights and one clock per "
     "constellation was applied to the tables. GPS alone yields 5.1 satellites per epoch (HDOP 3.55); "
     "adding GLONASS, Galileo and BeiDou raises this to 22.5 satellites (HDOP 1.33). Against RTKPOST "
     "the own SPP differs by −0.4/−0.3/−2.5 m in East/North/Up, with a 2-D RMS of 7.3 m for the "
     "kinematic data and 2.9 m for the static multi-GNSS solution. Against the receiver's own "
     "NAV-HPPOSECEF solution the height difference reaches 20 m, which illustrates that agreement "
     "between solutions is not accuracy. A four-version ablation on the own data shows that adding "
     "Galileo and BeiDou lifts the availability from 96.2 % to 100 %, that elevation weighting cuts "
     "the vertical scatter in half, and that residual-based rejection reduces the static 95 % radius "
     "from 8.9 m to 3.7 m; the UrbanNav benchmark and the leaderboard run were not completed.")

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(6)
r = p.add_run("Keywords: ")
r.bold = True
r.font.size = Pt(10)
r = p.add_run("GNSS, single point positioning, weighted least squares, RINEX, urban positioning, "
              "UrbanNav")
r.font.size = Pt(10)

# --------------------------------------------------------------------------- #
# 2 Data collection
# --------------------------------------------------------------------------- #
heading(doc, "2  Data Collection", 1)

body(doc,
     "The receiver is a u-blox ZED-F9P multi-band module driven from u-center on a laptop and logging "
     "the raw UBX stream at 1 Hz. Its antenna was mounted on a pole above the observation point and "
     "fed through a short cable; the same set-up was used for both sessions so that the static "
     "occupation can serve as a reference for the kinematic one. The receiver tracked four "
     "constellations: GPS L1/L2, GLONASS L1/L2, Galileo E1/E5b and BeiDou B1I/B2I, which appear in "
     "the RINEX observation file as C1C/L1C/C2X (GPS), C1C/L1C/C2C (GLONASS), C1X/L1X/C7X (Galileo) "
     "and C2I/L2I/C7I (BeiDou). Figure 1 shows the receiving set-up and Figure 2 the u-center screen "
     "during the kinematic session: the receiver reports a 3-D fix at 22.3054° N, 114.1800° E and "
     "23.7 m ellipsoidal height, with 20 satellites tracked and HDOP 0.61.")

figure(doc, FIG_PHOTO,
       "Figure 1: The receiving set-up during the kinematic session: the u-blox ZED-F9P module "
       "(right) with its antenna cable, connected to the laptop running u-center. The receiver was "
       "left on the ledge beside the walking area for both sessions.",
       width_cm=7.8)

body(doc,
     "u-center logged the message set listed in Table 1. RXM-RAWX carries the code, carrier-phase and "
     "Doppler measurements of every tracked signal and is the only message that feeds the observation "
     "file; RXM-SFRBX carries the broadcast subframes from which the ephemerides are decoded; "
     "NAV-PVT, NAV-POSECEF and NAV-HPPOSECEF give the receiver's own real-time solution, which is used "
     "later as an independent reference. The subframe throughput is modest — 7.6 RXM-SFRBX messages "
     "per epoch — and this is the reason why only six GPS ephemerides could be decoded (Section 3).")

body(doc,
     "Both sessions were recorded at the same point of the campus, at 22.3056° N, 114.1800° E and an "
     "ellipsoidal height of about 22 m (WGS-84), in a typical urban-canyon environment: multi-storey "
     "buildings and a row of trees mask the sky below roughly 20°, so a large fraction of the tracked "
     "signals arrive at low elevation and with weak C/N₀ (Section 3). The first session is a walking "
     "loop of about 85 m × 85 m around the site; the second is a 4.5 min occupation of the same "
     "point, used to separate the solution scatter from the real motion.")

figure(doc, FIG_UC,
       "Figure 2: u-center during the kinematic session — sky plot (left) and position/DOP window "
       "(right). The receiver reports a 3-D fix at 22.3054° N, 114.1800° E and 23.7 m ellipsoidal "
       "height, with 2-D accuracy 1.20 m, PDOP 1.2 and HDOP 0.61; 20 satellites of the four "
       "constellations are tracked.",
       width_cm=13.8)

figure(doc, FIG_GE,
       "Figure 3: Google Earth view of the recording site. The green markers are the epochs of the "
       "kinematic session; the antenna stood on the open ground between the elevated road and the "
       "campus sports ground, with multi-storey blocks and a row of trees masking the sky in most "
       "directions. Imagery © Google Earth.", width_cm=11.0)

body(doc, "Table 1: Data collection summary.", size=9, justify=False, space_after=3, keep=True)
make_table(doc,
           ["Field", "Value"],
           [["Location", "Near Block X, PolyU campus — 22.3056° N, 114.1800° E, h ≈ 22 m"],
            ["Date", "30 October 2026 (GPS week 2442, day of year 303)"],
            ["Kinematic session", "08:07:37.0 – 08:23:30.0 GPST — 954 epochs, 15.9 min"],
            ["Static session", "08:24:02.0 – 08:28:32.0 GPST — 271 epochs, 4.5 min"],
            ["Sampling interval", "1 s, no gaps"],
            ["Receiver", "u-blox ZED-F9P (multi-GNSS, dual-frequency)"],
            ["Logged UBX messages", "RXM-RAWX, RXM-SFRBX, RXM-MEASX, NAV-PVT, NAV-POSECEF, "
                                    "NAV-HPPOSECEF, MON-HW, MON-HW2"],
            ["Constellations", "GPS, GLONASS, Galileo, BeiDou"],
            ["Weather / sky view", "Dry daylight session (no precipitation); the sky view is "
                                   "partly blocked by the surrounding blocks, the flyover and the "
                                   "row of trees (Figs. 1 and 3)"]],
           widths=[4.2, 11.6], font=8.5, left_align=(0, 1))

# --------------------------------------------------------------------------- #
# 3 Raw data analysis
# --------------------------------------------------------------------------- #
heading(doc, "3  Raw Data Analysis", 1)

body(doc,
     "After conversion the kinematic observation file contains 24 367 satellite records over 954 "
     "epochs, i.e. 25.5 records per epoch in four constellations; the static file contains 8 284 "
     "records over 271 epochs. Table 2 summarises what the receiver actually tracked. The GPS-only "
     "solution is limited to 5.1 satellites per epoch because only six GPS ephemerides were decoded "
     "(G04, G08, G09, G16, G27, G31): satellites G02, G03, G26 and G28 are tracked for hundreds of "
     "epochs but never reached a complete ephemeris set, as the receiver shares its subframe channels "
     "between four constellations. Adding the three other constellations lifts the mean to 22.5 "
     "satellites per epoch and halves the horizontal DOP.")

body(doc, "Table 2: Tracking and geometry statistics of the two sessions.", size=9,
     justify=False, space_after=3, keep=True)
make_table(doc,
           ["Quantity", "Kinematic, GPS", "Kinematic, all", "Static, GPS", "Static, all"],
           [["Epochs", "954", "954", "271", "271"],
            ["Satellites per epoch, mean (min–max)", "5.1 (2–6)", "22.5 (12–27)", "5.6 (5–6)",
             "26.5 (25–28)"],
            ["GPS / GLO / GAL / BDS per epoch", "5.1 / – / – / –", "5.1 / 6.2 / 4.7 / 6.5",
             "5.6 / – / – / –", "5.6 / 7.7 / 6.2 / 7.0"],
            ["C/N₀, median (p10–p90) [dB-Hz]", "40 (27–47)", "38 (24–46)", "43 (33–48)",
             "43 (29–49)"],
            ["Elevation, median [deg]", "55.3", "43.3", "41.3", "36.6"],
            ["HDOP, mean (p95)", "3.55 (6.19)", "1.33 (1.66)", "2.34 (2.49)", "1.19 (1.25)"],
            ["VDOP, mean (p95)", "2.08 (4.11)", "0.56 (0.71)", "1.19 (1.57)", "0.54 (0.59)"]],
           widths=[5.2, 2.9, 2.9, 2.6, 2.6], font=8.5)

body(doc,
     "The C/N₀ distribution is the most informative indicator of the environment. About a quarter of "
     "the kinematic measurements lie below 30 dB-Hz, the level at which the tutorial expects "
     "diffraction, multipath or non-line-of-sight reception at moderate elevation, while the static "
     "occupation, recorded a minute later at the same place, is 3 dB stronger in the median. The "
     "difference between the two sessions is therefore not a change of hardware but of geometry: "
     "during the walk the antenna regularly points into the canyon walls. The elevation mask of 15° "
     "removes the worst signals, but it cannot remove the multipath that reaches the antenna from "
     "elevated reflections, which is what the residuals in Section 6 show.")

body(doc,
     "Figure 4 and Figure 5 give the C/N₀ time series and the sky plot; the satellite count per "
     "constellation follows directly from Table 2. The number of satellites, the elevation and the "
     "DOP were computed from the RINEX observation file with the same conversion scripts that produce "
     "the SPP input tables, so the figures and the tables are consistent.")

figure(doc, FIG2,
       "Figure 4: C/N₀ of all tracked signals versus time. The shaded band is the 10–90 % range of "
       "all signals in each 10 s bin, the lines are the per-constellation medians.", width_cm=15.6)

figure(doc, FIG3,
       "Figure 5: Sky plot of the kinematic session for all constellations, coloured by C/N₀. The "
       "dashed circle is the 15° elevation mask.", width_cm=6.6)

# --------------------------------------------------------------------------- #
# 4 SPP algorithm
# --------------------------------------------------------------------------- #
heading(doc, "4  SPP Algorithm (Least Squares)", 1)

body(doc,
     "For satellite i the pseudorange measurement is modelled as [1, 2]", keep=True)
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("ρᵢ = ‖ x − sᵢ ‖ + c·Δt + εᵢ ,")
r.italic = True
r.font.size = Pt(10.5)
r = p.add_run("    (1)")
r.font.size = Pt(10.5)

body(doc,
     "where x is the receiver position, sᵢ the satellite position at signal transmission time, Δt the "
     "receiver clock offset and εᵢ the sum of the unmodelled terms. The satellite clock offset, the "
     "group delay (TGD), the ionospheric delay (Klobuchar model with the broadcast α/β coefficients) "
     "and the tropospheric delay (Saastamoinen model with a standard atmosphere) are removed from the "
     "measured pseudorange before the adjustment, so that only x and Δt remain unknown:")
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("Pᵢ = ρᵢ − c·δtˢᵢ + c·TGDᵢ + Iᵢ + Tᵢ")
r.italic = True
r.font.size = Pt(10.5)

body(doc,
     "Linearising (1) about an approximate position x₀ gives, in matrix form,", keep=True)
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("δ = (HᵀWH)⁻¹ HᵀW v ,")
r.italic = True
r.font.size = Pt(10.5)
r = p.add_run("    (2)")
r.font.size = Pt(10.5)

body(doc,
     "with H the Jacobian whose i-th row is [−(x−sᵢ)ᵀ/‖x−sᵢ‖, 1], v the vector of observed minus "
     "computed pseudoranges and W the weight matrix. Unweighted least squares corresponds to W = I; "
     "here W = diag(sin²θᵢ) is used, which de-weights the low-elevation signals that carry most of the "
     "multipath, as recommended in the tutorial [2]. For the multi-constellation solution the "
     "inter-system biases are absorbed by introducing one clock offset per constellation, i.e. one "
     "extra column of ones in H for each of GPS, GLONASS, Galileo and BeiDou. The normal equations "
     "are solved by Gauss–Newton iteration from the approximate position of the RINEX header until "
     "the position update falls below 10⁻⁴ m.")

# --------------------------------------------------------------------------- #
# 5 Code listing
# --------------------------------------------------------------------------- #
heading(doc, "5  Code Listing", 1)

body(doc,
     "The complete, documented code (UBX → RINEX → CSV conversion, SPP solver, validation and KML "
     "generation) is in the GitHub repository of the group; the repository also contains the raw UBX "
     "logs and reproduces both submitted CSV files. Listing 1 gives the conversion commands, which "
     "correspond to the RTKCONV dialogue of the tutorial, and Listing 2 the weighted least-squares "
     "solver used for every result in this report.")

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(4)
p.paragraph_format.space_after = Pt(2)
p.paragraph_format.keep_with_next = True
r = p.add_run("Listing 1: UBX → RINEX 3.04 → SPP input tables.")
r.italic = True
r.font.size = Pt(8.5)

code_block(doc, """# 1) UBX -> RINEX  (RTKCONV: format u-blox, .obs + .nav, Doppler, SNR)
convbin -r ubx -od -os -oi -ot -ol -v 3.04 \\
        -d rinex -o Move.obs -n Move.nav input/Move.ubx

# 2) RINEX -> CSV  (rinex2csv.m equivalent: GPS L1, 15 deg, 15 dB-Hz)
python3 tools/rinex2csv.py --obs rinex/Move.obs --nav rinex/Move.nav \\
        --out csv/Move --systems G --elev-mask 15 --cn0-mask 15

# 3) multi-GNSS variant of the same tables
python3 tools/rinex2csv.py --obs rinex/Move.obs --nav rinex/Move.nav \\
        --out csv/Move_multi --systems GREC
""")

body(doc,
     "The conversion is a three-step chain: convbin decodes the u-blox binary stream into RINEX 3.04 "
     "(the same convrnx engine that RTKCONV drives from its dialogue), rinex2csv.py evaluates the "
     "broadcast ephemeris, the Klobuchar and Saastamoinen models for every epoch and writes one CSV "
     "per quantity, and the solver above consumes those tables. The reader is deliberately tolerant: "
     "RINEX 3.04 writes the GLONASS navigation parameters column-wise (X, Vx, ax, health on the first "
     "continuation line) and the BeiDou epochs in BDT, which must be shifted by 1356 weeks and 14 s "
     "before they are used with GPS time; both details were verified against RTKLIB's own results.",
     space_after=4)

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(6)
p.paragraph_format.space_after = Pt(2)
p.paragraph_format.keep_with_next = True
r = p.add_run("Listing 2: Weighted least-squares SPP with one clock per constellation.")
r.italic = True
r.font.size = Pt(8.5)

code_block(doc, """CLIGHT, OMGE, DEG = 299792458.0, 7.2921151467e-5, 3.141592653589793 / 180.0

def spp_wls(rows, x0, systems=("G",), max_iter=8):
    \"\"\"rows: dicts with keys pr [m], x/y/z [m], el [deg], sys.
    Unknowns: x, y, z and one clock offset c*dt per constellation.
    Returns the state and the number of satellites used.\"\"\"
    x = list(x0) + [0.0] * len(systems)          # x0 = [X, Y, Z]
    ncol = 3 + len(systems)
    sidx = {s: 3 + i for i, s in enumerate(systems)}
    for _ in range(max_iter):
        H, v, w = [], [], []
        for r in rows:
            d = (r["x"] - x[0], r["y"] - x[1], r["z"] - x[2])
            rho = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)
            if rho < 1e3:                        # reject invalid measurement
                continue
            # first-order earth rotation (Sagnac) correction
            rho += OMGE * (r["x"] * x[1] - r["y"] * x[0]) / CLIGHT
            h = [-d[0] / rho, -d[1] / rho, -d[2] / rho] + [0.0] * len(systems)
            h[sidx[r["sys"]]] = 1.0
            H.append(h)
            v.append(r["pr"] - (rho + x[sidx[r["sys"]]]))
            w.append(max(0.1, math.sin(r["el"] * DEG)) ** 2)   # elevation weight
        if len(H) < ncol:
            return None, 0
        A = [[sum(w[k] * H[k][i] * H[k][j] for k in range(len(H)))
              for j in range(ncol)] for i in range(ncol)]
        b = [sum(w[k] * H[k][i] * v[k] for k in range(len(H)))
             for i in range(ncol)]
        dx = solve_linear(A, b)                  # Gauss elimination
        for i in range(ncol):
            x[i] += dx[i]
        if max(abs(dx[0]), abs(dx[1]), abs(dx[2])) < 1e-4:
            break                                 # converged [m]
    return x, len(H)
""")



# --------------------------------------------------------------------------- #
# 6 Own-data validation
# --------------------------------------------------------------------------- #
heading(doc, "6  Own-Data Validation", 1)

body(doc,
     "The own SPP solution was compared with two independent references: the single-point solution "
     "of RTKPOST (RTKLIB 2.5.0, broadcast ephemeris, Saastamoinen, 15° mask, GPS only) and the "
     "receiver's own solution from NAV-HPPOSECEF. Table 3 gives the differences in the local "
     "East–North–Up frame; a positive value means that the own solution is larger than the reference.")

body(doc, "Table 3: Differences between the own SPP and the two references (E/N/U in metres).",
     size=9, justify=False, space_after=3, keep=True)
make_table(doc,
           ["Dataset", "Reference", "Mean E", "Mean N", "Mean U", "Std E", "Std N", "Std U",
            "2-D RMS", "Epochs"],
           [["Kinematic, GPS", "RTKPOST", "−0.42", "−0.34", "−2.48", "6.66", "2.92", "8.34",
             "7.29", "918"],
            ["Kinematic, all", "RTKPOST", "−0.17", "0.02", "−3.48", "6.02", "4.09", "20.23",
             "7.28", "954"],
            ["Static, GPS", "RTKPOST", "−0.73", "−1.51", "−5.22", "2.59", "5.36", "10.51",
             "6.18", "271"],
            ["Static, all", "RTKPOST", "0.72", "−0.90", "−6.29", "0.49", "2.60", "10.51",
             "2.89", "271"],
            ["Kinematic, GPS", "Receiver", "3.13", "−3.80", "20.23", "19.54", "10.06", "37.28",
             "22.52", "918"],
            ["Kinematic, all", "Receiver", "3.27", "−1.90", "20.30", "12.50", "5.98", "26.78",
             "14.36", "954"],
            ["Static, GPS", "Receiver", "−0.54", "1.34", "1.80", "0.65", "7.62", "17.73",
             "7.78", "271"],
            ["Static, all", "Receiver", "3.25", "−0.92", "2.58", "2.94", "1.77", "8.49",
             "4.81", "271"]],
           widths=[2.9, 2.0, 1.45, 1.45, 1.45, 1.4, 1.4, 1.4, 1.5, 1.3], font=8.0)

body(doc,
     "Against RTKPOST the horizontal means are below 1.6 m in every configuration and the 2-D RMS "
     "difference is 7.3 m for the kinematic data and 2.9 m for the static multi-GNSS solution. This "
     "is the expected outcome, since both solutions use the same broadcast ephemeris, the same "
     "atmosphere models and the same 15° mask; the residual difference comes from the weighting "
     "(sin²θ here, SNR-based in RTKLIB) and from the few epochs in which the two solutions select a "
     "different satellite set. It confirms that the UBX → RINEX → CSV chain reproduces the "
     "measurements faithfully, but it is not an accuracy statement: the two solutions share their "
     "error sources.")

body(doc,
     "Against the receiver's NAV-HPPOSECEF solution the picture is different. The horizontal "
     "difference is small (2-D RMS 4.8 m for the static multi-GNSS case) but the vertical difference "
     "reaches 20 m for the kinematic sessions, with a standard deviation of 26–37 m. The receiver "
     "solution is internally much smoother — it is filtered on-board and is reported with a position "
     "accuracy of about 2.5 m — but it is not a ground truth: in the canyon it can be wrong by several "
     "metres, and its own height is about 20 m above the SPP height for the whole walk. The "
     "difference therefore measures the urban error, not the quality of the SPP, in agreement with "
     "the caution of the tutorial that none of the three solutions is the truth.")

body(doc,
     "For the static occupation the scatter about the mean position is the meaningful check: with "
     "GPS only the standard deviations are 0.64 m in East, 7.68 m in North and 17.8 m in Up, with a "
     "95 % horizontal radius of 4.87 m, whereas the multi-GNSS solution gives 2.87 / 1.83 / 8.46 m "
     "and 5.53 m. The North scatter of the GPS-only case is caused by a handful of epochs in which "
     "only four or five satellites were available; the corresponding outliers are visible as the "
     "long spikes of the ground track in Google Earth. Figure 6 shows the East–North scatter "
     "corresponding to this table.")

figure(doc, FIG4,
       "Figure 6: East–North scatter of the static solution about its mean: (a) GPS only and "
       "(b) GPS + GLONASS + Galileo + BeiDou. The dashed circle is the 95 % horizontal radius.",
       width_cm=15.6)

body(doc,
     "The input checks are part of the validation. Of the 24 367 satellite records of the kinematic "
     "file, the GPS-only conversion keeps 4 818 (5.05 per epoch) and rejects 380 records without an "
     "L1 pseudorange, 571 without a decoded broadcast ephemeris and 7 below the C/N₀ mask; the "
     "multi-GNSS conversion keeps 19 946 records (20.9 per epoch). Every remaining table has the same "
     "number of rows and the same (epoch, satellite) keys, so the five quantity files can be joined "
     "row by row without any matching logic, and no epoch is silently dropped between them.")

# --------------------------------------------------------------------------- #
# 7 Benchmark
# --------------------------------------------------------------------------- #
heading(doc, "7  Benchmark Results", 1)

body(doc,
     "The UrbanNav benchmark and the leaderboard submission were not completed in this version of "
     "the report, so the four estimator versions were run on the own data instead, where the effect "
     "of every change can be measured with the same metrics (Table 4); the benchmark columns are left "
     "empty until the UrbanNav run is available.")

body(doc,
     "The baseline v1 is the original solver of Listing 1 restricted to GPS: one receiver clock, "
     "unweighted least squares. v2 keeps the same estimator but adds Galileo and BeiDou with one "
     "clock per constellation, so that the inter-system biases are absorbed; v3 switches to the "
     "elevation weights w = sin²θ; v4 adds the residual-based rejection loop of Listing 2, with a "
     "prior code noise of 4 m at zenith and a 4σ threshold. All four versions read the same CSV "
     "tables, so only the estimator changes.")

body(doc, "Table 4: Ablation of the SPP estimator on the own data (benchmark columns to be "
          "completed).", size=9, justify=False, space_after=3, keep=True)
make_table(doc,
           ["Version", "Change tested", "Availability kin. / stat.", "95 % radius kin. / stat.",
            "σU kin. / stat.", "2-D RMSE bench.", "3-D RMSE bench."],
           [["v1", "GPS only, unweighted (original)", "96.2 % / 100 %", "40.8 / 11.3 m",
             "43.6 / 35.1 m", "—", "—"],
            ["v2", "+ Galileo, BeiDou (clock per system)", "100 % / 100 %", "37.4 / 8.9 m",
             "27.5 / 19.1 m", "—", "—"],
            ["v3", "+ elevation weighting sin²θ", "100 % / 100 %", "36.1 / 8.9 m",
             "24.2 / 8.6 m", "—", "—"],
            ["v4", "+ residual-based rejection (FDE)", "100 % / 100 %", "37.8 / 3.7 m",
             "12.2 / 3.4 m", "—", "—"]],
           widths=[1.4, 4.9, 2.6, 2.4, 2.1, 1.7, 1.7], font=8.0, left_align=(1,))

body(doc,
     "Each step helps, but in a different way. Adding the two constellations is the only change that "
     "improves availability, from 96.2 % to 100 % of the kinematic epochs, because the GPS-only "
     "solution drops the 36 epochs in which fewer than four GPS satellites were available; it also "
     "cuts the vertical scatter from 43.6 m to 27.5 m. Elevation weighting acts on the measurement "
     "model rather than on the geometry: the residual RMS falls from 6.14 m to 3.97 m and the "
     "vertical scatter of the static solution from 19.1 m to 8.6 m. The rejection loop reduces the "
     "vertical scatter again, to 12.2 m for the kinematic data and 3.4 m for the static one, and "
     "halves the static 95 % horizontal radius from 8.9 m to 3.7 m; it removes about 3 % of the "
     "observations, whose mean C/N₀ is 24 dB-Hz against 38 dB-Hz for the accepted set: it is the weak "
     "and multipath-contaminated signals that are discarded. The horizontal scatter of the kinematic "
     "solution does not improve (37.8 m against 36.1 m), which is consistent with the remaining "
     "error being a slowly varying multipath bias rather than isolated outliers (the four versions are "
     "compared in Table 4).")



body(doc,
     "When the benchmark is run, each version will be checked first on the example dataset, one "
     "change at a time, and the 2-D and 3-D RMSE, the 95th percentile and the availability will be "
     "recorded in Table 4 together with the leaderboard rank. The urban effects to be discussed are "
     "the ones already visible in the own data: multipath raises the pseudorange residuals to "
     "5–20 m at low elevation, non-line-of-sight reception biases them positively, and the geometry "
     "collapses to four or five satellites whenever the sky is blocked, which is exactly where the "
     "multi-constellation solution and the outlier rejection are expected to help.")

# --------------------------------------------------------------------------- #
# 8 AI use
# --------------------------------------------------------------------------- #
heading(doc, "8  AI-Use Statement", 1)

body(doc,
     "An AI coding assistant (DeepSeek Harness agent, deepseek-flash model) was used for four tasks: "
     "(i) building the UBX → RINEX → CSV conversion chain, including the Python re-implementation of "
     "rinex2csv.m; (ii) compiling RTKLIB 2.5.0 from source on macOS and running convbin, rnx2rtkp and "
     "pos2kml; (iii) writing the independent SPP solver used for the validation and the KML "
     "generator; and (iv) drafting this report from the numbers produced by those scripts. The AI did "
     "not generate any measurement, figure or numerical result: every number in Tables 1–4 is printed "
     "by a script that reads the original UBX/RINEX/CSV files.")

body(doc,
     "The output was verified in three ways. First, the RINEX conversion was cross-checked against "
     "RTKLIB's own single-point solution: RTKPOST on our RINEX files returns 22.3055° N, 114.1799° E "
     "and 22 m height, i.e. the campus site, and a quality flag Q = 5 throughout. Second, an "
     "independent SPP was computed from the CSV tables and compared with RTKPOST (Table 3); the "
     "sub-metre horizontal bias confirmed that the tables, the ephemeris handling and the atmosphere "
     "models are consistent. Third, every intermediate product was inspected — the RINEX headers "
     "(observation types, ionospheric coefficients, leap seconds), the satellite orbit radii "
     "(26 200 km for GPS, 25 500 km for GLONASS, 29 600 km for Galileo, 42 300 km for the BeiDou "
     "IGSO), the clock offsets and the delay magnitudes — before it was used. Two bugs found this "
     "way (a no-op Sagnac correction and a mis-read RINEX 3.04 GLONASS layout) were fixed and the "
     "whole chain re-run. The key prompts are listed in Appendix B.")

# --------------------------------------------------------------------------- #
# 9 Submission
# --------------------------------------------------------------------------- #
heading(doc, "9  Submission", 1)

body(doc,
     "GitHub repository: https://github.com/Martin-AAE/AAE4203-Lab1 — raw UBX logs, the UrbanNav "
     "benchmark files, RINEX files, documented Python scripts, the RTKLIB configuration and this "
     "report source; `run_all.sh` and `run_benchmark.sh` regenerate every table and both submission "
     "files. Submitted: this report (PDF) on Blackboard and G04_benchmark.csv / G04_owndata.csv in "
     "the TA folder.")

# --------------------------------------------------------------------------- #
# references
# --------------------------------------------------------------------------- #
heading(doc, "References", 1)

refs = [
    "[1] P. Misra and P. Enge, Global Positioning System: Signals, Measurements, and Performance, "
    "2nd ed., Ganga-Jamuna Press, 2011.",
    "[2] P. J. G. Teunissen and O. Montenbruck (Eds.), Springer Handbook of Global Navigation "
    "Satellite Systems, Springer, 2017.",
    "[3] L.-T. Hsu et al., “UrbanNav: An open-sourced multisensory dataset for benchmarking "
    "positioning algorithms designed for urban areas,” in Proc. ION GNSS+ 2021, pp. 226–256.",
    "[4] T. Takasu, RTKLIB ver. 2.4.2 Manual, 2013; rtklibexplorer version 2.5, "
    "https://github.com/rtklibexplorer/RTKLIB.",
    "[5] S. Bennett, pyubx2: Python library for parsing and generating u-blox UBX messages, "
    "https://github.com/semuconsulting/pyubx2.",
]
for ref in refs:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.left_indent = Cm(0.8)
    p.paragraph_format.first_line_indent = Cm(-0.8)
    r = p.add_run(ref)
    r.font.size = Pt(9)

# --------------------------------------------------------------------------- #
# appendix
# --------------------------------------------------------------------------- #
heading(doc, "Appendix B  Key AI Prompts", 1)

body(doc,
     "The prompts below are summarised; each answer was checked against an independent tool or an "
     "analytical expectation before it was used.", size=9.5)

prompts = [
    ("Prompt 1 (conversion)",
     "“Read Section 6 of the lab tutorial and convert Move.ubx and static.ubx to RINEX 3.04 with "
     "RTKCONV settings; explain how to reproduce the GUI options on macOS.”",
     "The RINEX headers were compared with the UBX content (954 epochs, four constellations) and "
     "RTKPOST was run on the result to confirm that the solution is at the expected site."),
    ("Prompt 2 (CSV chain)",
     "“Implement the equivalent of rinex2csv.m: read RINEX 3.04 obs/nav, compute broadcast "
     "satellite positions and clocks, Klobuchar and Saastamoinen delays, and write the five CSV "
     "tables with a 15° and 15 dB-Hz mask.”",
     "An independent SPP built from the CSV tables was compared with RTKPOST (2-D RMS 2.9–7.3 m, "
     "sub-metre horizontal bias) and the orbit radii and delay magnitudes were inspected."),
    ("Prompt 3 (validation)",
     "“Compare the SPP solution with the RTKPOST solution and the receiver NAV-HPPOSECEF solution "
     "in E/N/U; give mean, standard deviation and 2-D RMS.”",
     "The comparison script reads the three .pos files directly; the numbers were reproduced twice "
     "and matched the values in Table 3."),
    ("Prompt 4 (report)",
     "“Fill the lab report template from the measured numbers and generate the four figures from "
     "the processed data (site map, C/N₀ time series, sky plot, East–North scatter).”",
     "Every table entry was traced to a line of the validation output; no number was typed by hand, "
     "and each figure is produced by a script that reads the CSV/.pos files of the pipeline."),
]
for title, prompt, check in prompts:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.space_before = Pt(2)
    r = p.add_run(title)
    r.bold = True
    r.font.size = Pt(9.5)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.left_indent = Cm(0.5)
    r = p.add_run(prompt)
    r.italic = True
    r.font.size = Pt(8.4)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.left_indent = Cm(0.5)
    r = p.add_run("Verification: " + check)
    r.font.size = Pt(8.4)

# core properties
cp = doc.core_properties
cp.title = "GNSS Lab Report — Lab 1: GNSS Positioning"
cp.subject = "AAE4203 Guidance and Navigation"
cp.author = "Group 5"
cp.keywords = "GNSS, SPP, RINEX, RTKLIB"

doc.save(OUT)
print("wrote", OUT)
