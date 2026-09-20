"""Re-runnable version of the "dataviz validator" DESIGN.md tells you to re-run.

DESIGN.md 5b says the plotted colours were run through a validator in both
modes and "do not hand-tune them, and re-run the validator if you change one".
That instruction was unmeetable: the validator was an external tool and never
landed in the repo, so the only thing standing between a future edit and a
quietly-worse palette was a comment asking nicely.

This is the validator, in the repo, reading the tokens out of the template so
it can never hold its own stale copy of the palette. It answers one question:
is this pair of colours still tellable apart, by everyone, on this surface?

WHAT IT CHECKS, per pair per mode

  lightness band   OKLCH L of each colour inside a band. A plotted colour that
                   is nearly as light as the surface disappears into it; one at
                   the other extreme reads as an outline, not a fill.
  chroma floor     OKLCH C of each colour above a floor. A desaturated "red"
                   stops being read as a category and starts being read as a
                   shade of grey.
  normal vision    CIEDE2000 between the two, for a reader with no deficiency.
  CVD separation   CIEDE2000 between the two as seen under protanopia,
                   deuteranopia and tritanopia (Machado 2009, severity 1.0).
                   This is the check green/red classically fails and the reason
                   the original palette chose blue/red for the candles.
  surface contrast WCAG 2.1 contrast of each colour against the surface it is
                   actually drawn on in that mode.

WHERE THE THRESHOLDS COME FROM

  Not from memory, and not from a number that sounded right. Every floor below
  is the weakest value achieved by the palette that already passed the original
  external validator, measured by this file and rounded down. So the bar is
  exactly "no worse than the palette that was recorded as passing" - a claim
  this repo can re-derive from its own git history rather than take on trust.

  The one number that came from outside is the counter-example recorded in the
  template at the MA-colour comment: a fifth hue (purple) was rejected against
  the up-candle blue at dE 10.7. That is a FAILING value, so the normal-vision
  floor must sit above it, and it does.

USAGE
  py tools/palette_check.py            check, exit 1 on any failure
  py tools/palette_check.py --report   print every measured number, always exit 0
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "dashboard.tmpl.html"

# The page asks its colours to do two different jobs, and the original palette
# failed both by conflating them.
#
#   MARK_PAIRS  drawn as shapes - candle bodies, treemap tiles, bars. Colour
#               can be the only channel, so CVD separation is load-bearing.
#               Owes >=3:1 against its surface, not readable-text contrast.
#
#   TEXT_TOKENS every signed number and every label. Always carries a + or -
#               glyph beside it, so colour is redundant and CVD separation is
#               NOT load-bearing - but it is text, so it owes WCAG AA.
#
# Checking the mark pair for readability, or the text pair for CVD, is how you
# get a palette that passes the check it was measured against and fails the one
# that actually applied to it.
# The four hues on the price chart share one plot, so the honest check is all
# six pairs among them, not the two DESIGN.md recorded. Two was enough only
# while up was blue and target was green - the two greens never met. Gain is
# green now, which puts a green candle body and a green target line on the same
# axes, and that pair has to be measured like any other.
PLOTTED = ["up", "down", "target", "trigger"]

# ...with one exemption, and only one. Target and trigger are dashed/solid and
# carry their own axis labels, so a reader who cannot separate the hues still
# reads the chart. Every pair involving a candle body IS colour-alone: nothing
# else distinguishes a filled green body from a filled red one.
NOT_COLOUR_ALONE = {frozenset(("target", "trigger"))}

MARK_PAIRS = [
    (f"plot {a}/{b}", a, b, frozenset((a, b)) not in NOT_COLOUR_ALONE)
    for i, a in enumerate(PLOTTED) for b in PLOTTED[i + 1:]
] + [
    ("treemap pos/neg", "pos", "neg", True),
]

# Every token used for text, checked against every surface it can land on.
# --muted is the one this catches: it was tuned once against the dark plane and
# the same hex was pasted into the light block, where it reads at 3.41:1.
TEXT_TOKENS = ["ink", "ink-2", "muted", "good-ink", "warn-ink", "crit-ink"]
SURFACES = ["surface-1", "surface-2", "plane"]

# Floors, derived by this file from the palette recorded as passing. See the
# module docstring: these are that palette's own weakest values, rounded down.
L_BAND = (0.35, 0.80)   # OKLCH lightness
C_FLOOR = 0.07          # OKLCH chroma
DE_NORMAL = 11.0        # CIEDE2000, normal vision. Above the recorded dE 10.7 reject.
DE_CVD = 9.0            # CIEDE2000, worst of protan/deutan/tritan
CONTRAST_FLOOR = 3.0    # WCAG, a mark against every surface it is drawn on
AA_TEXT = 4.5           # WCAG 2.1 AA, normal-size text. Not derived - it is the
                        # published threshold, and the page renders labels at
                        # 11px, so the large-text 3:1 allowance never applies.


# --------------------------------------------------------------- colour math

def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def parse_hex(h: str) -> tuple[float, float, float]:
    h = h.strip().lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore


def to_linear(rgb):
    return tuple(srgb_to_linear(c) for c in rgb)


def oklab(lin) -> tuple[float, float, float]:
    """Linear sRGB -> OKLab (Bjorn Ottosson, 2020)."""
    r, g, b = lin
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def oklch(lin) -> tuple[float, float]:
    """Returns (L, C). Hue is not checked - only separation is."""
    L, a, b = oklab(lin)
    return L, math.hypot(a, b)


def xyz_d65(lin) -> tuple[float, float, float]:
    r, g, b = lin
    return (0.4123908 * r + 0.3575843 * g + 0.1804808 * b,
            0.2126390 * r + 0.7151687 * g + 0.0721923 * b,
            0.0193308 * r + 0.1191948 * g + 0.9505322 * b)


def lab_d65(lin) -> tuple[float, float, float]:
    """CIELAB, D65 white point - the space CIEDE2000 is defined on."""
    xn, yn, zn = 0.9504559, 1.0000000, 1.0890578
    x, y, z = xyz_d65(lin)

    def f(t):
        return t ** (1 / 3) if t > 216 / 24389 else (841 / 108) * t + 4 / 29

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def ciede2000(lab1, lab2) -> float:
    """CIEDE2000 colour difference. Sharma, Wu & Dalal (2005) formulation."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cbar = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cbar ** 7 / (Cbar ** 7 + 25 ** 7))) if Cbar > 0 else 0.5
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if (a1p or b1) else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if (a2p or b2) else 0.0

    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp) / 2)

    Lbar = (L1 + L2) / 2
    Cbarp = (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbarp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbarp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbarp = (h1p + h2p + 360) / 2
    else:
        hbarp = (h1p + h2p - 360) / 2

    T = (1 - 0.17 * math.cos(math.radians(hbarp - 30))
         + 0.24 * math.cos(math.radians(2 * hbarp))
         + 0.32 * math.cos(math.radians(3 * hbarp + 6))
         - 0.20 * math.cos(math.radians(4 * hbarp - 63)))
    dtheta = 30 * math.exp(-(((hbarp - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cbarp ** 7 / (Cbarp ** 7 + 25 ** 7)) if Cbarp > 0 else 0.0
    Sl = 1 + (0.015 * (Lbar - 50) ** 2) / math.sqrt(20 + (Lbar - 50) ** 2)
    Sc = 1 + 0.045 * Cbarp
    Sh = 1 + 0.015 * Cbarp * T
    Rt = -math.sin(math.radians(2 * dtheta)) * Rc

    return math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2
                     + Rt * (dCp / Sc) * (dHp / Sh))


# Machado, Oliveira & Fernandes (2009), severity 1.0, applied to LINEAR sRGB.
CVD_MATRICES = {
    "protan": ((0.152286, 1.052583, -0.204868),
               (0.114503, 0.786281, 0.099216),
               (-0.003882, -0.048116, 1.051998)),
    "deutan": ((0.367322, 0.860646, -0.227968),
               (0.280085, 0.672501, 0.047413),
               (-0.011820, 0.042940, 0.968881)),
    "tritan": ((1.255528, -0.076749, -0.178779),
               (-0.078411, 0.930809, 0.147602),
               (0.004733, 0.691367, 0.303900)),
}


def simulate(lin, kind: str):
    m = CVD_MATRICES[kind]
    return tuple(max(0.0, min(1.0, sum(m[i][j] * lin[j] for j in range(3))))
                 for i in range(3))


def relative_luminance(lin) -> float:
    r, g, b = lin
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(lin_a, lin_b) -> float:
    la, lb = relative_luminance(lin_a), relative_luminance(lin_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ------------------------------------------------------------- token reading

def read_tokens(text: str) -> dict[str, dict[str, str]]:
    """Pull the :root token blocks out of the template.

    The light block is the bare `:root{...}`; the dark values are taken from
    `:root[data-theme="dark"]{...}`. The prefers-color-scheme block is a
    duplicate of the latter and is checked for agreement rather than read
    twice - two copies of a palette that disagree is its own defect.
    """
    def block(pattern: str) -> dict[str, str]:
        m = re.search(pattern, text, re.S | re.M)
        if not m:
            raise SystemExit(f"palette block not found: {pattern}")
        return dict(re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})", m.group(1)))

    light = block(r"^:root\{(.*?)\n\}")
    dark = block(r':root\[data-theme="dark"\]\{(.*?)\n\}')
    media = block(r'@media \(prefers-color-scheme: dark\)\{[^{]*\{(.*?)\n\}\}')

    drift = {k for k in dark if media.get(k) != dark[k]} | {k for k in media if k not in dark}
    if drift:
        raise SystemExit("the two dark palette blocks disagree on: "
                         + ", ".join(sorted(drift)))
    return {"light": light, "dark": dark}


# ------------------------------------------------------------------- checking

class Result:
    def __init__(self):
        self.rows: list[tuple] = []
        self.failures: list[str] = []

    def check(self, mode, pair, metric, value, ok, bar):
        self.rows.append((mode, pair, metric, value, ok, bar))
        if not ok:
            self.failures.append(f"{mode}/{pair}: {metric} = {value:.2f} (needs {bar})")


def worst_contrast(lin, pal) -> float:
    """Contrast against the least forgiving surface the token can land on.

    Checking against one surface is how --muted came to pass: it was measured
    against the plane it was designed for and never against the two others it
    is also drawn on.
    """
    return min(contrast(lin, to_linear(parse_hex(pal[s])))
               for s in SURFACES if s in pal)


def evaluate(tokens) -> Result:
    res = Result()
    for mode, pal in tokens.items():
        for label, ka, kb, colour_alone in MARK_PAIRS:
            missing = [k for k in (ka, kb) if k not in pal]
            if missing:
                res.failures.append(f"{mode}/{label}: token(s) missing: {missing}")
                continue
            a = to_linear(parse_hex(pal[ka]))
            b = to_linear(parse_hex(pal[kb]))

            for name, lin in ((ka, a), (kb, b)):
                L, C = oklch(lin)
                res.check(mode, label, f"L({name})", L,
                          L_BAND[0] <= L <= L_BAND[1], f"{L_BAND[0]}-{L_BAND[1]}")
                res.check(mode, label, f"C({name})", C, C >= C_FLOOR, f">={C_FLOOR}")
                k = worst_contrast(lin, pal)
                res.check(mode, label, f"contrast({name})", k,
                          k >= CONTRAST_FLOOR, f">={CONTRAST_FLOOR}")

            de = ciede2000(lab_d65(a), lab_d65(b))
            res.check(mode, label, "dE normal", de, de >= DE_NORMAL, f">={DE_NORMAL}")
            for kind in CVD_MATRICES:
                d = ciede2000(lab_d65(simulate(a, kind)), lab_d65(simulate(b, kind)))
                # A pair that carries a second channel is still measured and
                # still printed by --report - it just cannot fail the build on
                # the CVD number alone, because hue is not what separates it.
                res.check(mode, label, f"dE {kind}", d,
                          d >= DE_CVD or not colour_alone,
                          f">={DE_CVD}" if colour_alone else "n/a (line style + label)")

        for tok in TEXT_TOKENS:
            if tok not in pal:
                res.failures.append(f"{mode}/text: token missing: --{tok}")
                continue
            k = worst_contrast(to_linear(parse_hex(pal[tok])), pal)
            res.check(mode, "text", f"AA(--{tok})", k, k >= AA_TEXT, f">={AA_TEXT}")
    return res


def score_pair(hex_a: str, hex_b: str, hex_surface: str) -> int:
    """Score one candidate pair against the same floors, without the template.

    This is the loop the original external validator existed to serve: you have
    a colour in mind, and you want to know whether it survives before it is
    anywhere near a commit.
    """
    res = Result()
    a, b = to_linear(parse_hex(hex_a)), to_linear(parse_hex(hex_b))
    surf = to_linear(parse_hex(hex_surface))
    for name, lin in ((hex_a, a), (hex_b, b)):
        L, C = oklch(lin)
        res.check("candidate", "pair", f"L({name})", L,
                  L_BAND[0] <= L <= L_BAND[1], f"{L_BAND[0]}-{L_BAND[1]}")
        res.check("candidate", "pair", f"C({name})", C, C >= C_FLOOR, f">={C_FLOOR}")
        res.check("candidate", "pair", f"contrast({name})", contrast(lin, surf),
                  contrast(lin, surf) >= CONTRAST_FLOOR, f">={CONTRAST_FLOOR}")
    de = ciede2000(lab_d65(a), lab_d65(b))
    res.check("candidate", "pair", "dE normal", de, de >= DE_NORMAL, f">={DE_NORMAL}")
    for kind in CVD_MATRICES:
        d = ciede2000(lab_d65(simulate(a, kind)), lab_d65(simulate(b, kind)))
        res.check("candidate", "pair", f"dE {kind}", d, d >= DE_CVD, f">={DE_CVD}")

    w = max(len(r[2]) for r in res.rows)
    for _, _, metric, value, ok, bar in res.rows:
        print(f"   {metric:<{w}}  {value:7.2f}  {'ok  ' if ok else 'FAIL'}  {bar}")
    print(f"\n{hex_a} / {hex_b} on {hex_surface}: "
          + ("PASS" if not res.failures else f"FAIL ({len(res.failures)})"))
    return 1 if res.failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true",
                    help="print every measured number and always exit 0")
    ap.add_argument("--pair", nargs=3, metavar=("HEX_A", "HEX_B", "SURFACE"),
                    help="score a candidate pair against the same floors "
                         "WITHOUT editing the template, so a colour can be "
                         "rejected before it is committed")
    args = ap.parse_args()

    if args.pair:
        return score_pair(*args.pair)

    tokens = read_tokens(TEMPLATE.read_text(encoding="utf-8"))
    res = evaluate(tokens)

    if args.report:
        w = max(len(r[2]) for r in res.rows)
        last = None
        for mode, pair, metric, value, ok, bar in res.rows:
            if (mode, pair) != last:
                print(f"\n{mode:5s}  {pair}")
                last = (mode, pair)
            print(f"   {metric:<{w}}  {value:7.2f}  {'ok  ' if ok else 'FAIL'}  {bar}")
        print()
        return 0

    if res.failures:
        print(f"palette FAIL - {len(res.failures)} of {len(res.rows)} checks")
        for f in res.failures:
            print(f"  {f}")
        print("\nDESIGN.md 5b: the plotted colours are computed, not chosen.")
        return 1

    print(f"palette ok - {len(res.rows)} checks across "
          f"{len(tokens)} modes and {len(MARK_PAIRS)} pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
