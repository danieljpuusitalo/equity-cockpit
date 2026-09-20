"""Squarified treemap layout, computed here rather than in the browser.

The page displays and does not decide, so the rectangles arrive already
placed. Everything below is pure arithmetic on a list of (key, value) pairs
and has no idea what a position is.

The algorithm is Bruls, Huizing and van Wijk's squarified treemap: fill the
shorter side of the remaining space with a row, adding tiles to that row only
while doing so improves the worst aspect ratio in it. The naive alternative -
slice-and-dice - produces correct areas as slivers one pixel wide, which is
area you cannot read, label or click. Aspect ratio is the whole point.

Coordinates are returned in the same units the caller passes in. The caller
uses percentages, so the page can place tiles with `style="left:..%"` and stay
responsive without recomputing anything.
"""


def _worst(row, side):
    """Worst aspect ratio in `row` if it is laid along an edge of `side`.

    Both orientations are checked because a row can be too wide or too tall
    and only the worse of the two tells you whether to stop adding to it.
    """
    total = sum(row)
    if total <= 0 or side <= 0:
        return float("inf")
    return max((side * side * max(row)) / (total * total),
               (total * total) / (side * side * min(row)))


def squarify(items, width=100.0, height=100.0):
    """Lay `items` - a list of (key, value) - into `width` x `height`.

    Returns a list of {key, x, y, w, h}, largest first. Tile area is exactly
    proportional to value, so the picture cannot mislead about size.

    A value that is None or <= 0 is DROPPED, never coerced to a floor so it
    still draws. A position worth nothing has no area, and inventing one pixel
    for it would put a name on this map that the book does not really hold.
    The caller is expected to report the drop rather than let the tiles quietly
    sum to less than the book - see `overview.allocation`.
    """
    vals = sorted(((k, float(v)) for k, v in items if v is not None and v > 0),
                  key=lambda kv: -kv[1])
    if not vals:
        return []

    total = sum(v for _, v in vals)
    scale = (width * height) / total
    vals = [(k, v * scale) for k, v in vals]

    out = []
    x, y, w, h = 0.0, 0.0, float(width), float(height)
    while vals:
        side = min(w, h)
        # Grow the row while the worst tile in it keeps getting squarer. The
        # first tile always joins: a row of one is the baseline to beat.
        n = 1
        while n < len(vals):
            row = [v for _, v in vals[:n]]
            if _worst([v for _, v in vals[:n + 1]], side) > _worst(row, side):
                break
            n += 1
        row, vals = vals[:n], vals[n:]
        span = sum(v for _, v in row)

        if w >= h:                      # row runs down the left edge
            rw = span / h if h else 0.0
            oy = y
            for key, v in row:
                rh = (v / span) * h if span else 0.0
                out.append({"key": key, "x": x, "y": oy, "w": rw, "h": rh})
                oy += rh
            x, w = x + rw, w - rw
        else:                           # row runs across the top edge
            rh = span / w if w else 0.0
            ox = x
            for key, v in row:
                rw = (v / span) * w if span else 0.0
                out.append({"key": key, "x": ox, "y": y, "w": rw, "h": rh})
                ox += rw
            y, h = y + rh, h - rh

    return out
