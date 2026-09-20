"""The treemap layout: areas must be honest, tiles must be readable.

A treemap is a picture that claims "this rectangle is this fraction of the
book". If the areas drift, the picture lies in a way no number on the page
contradicts. These tests pin the two properties that make it trustworthy -
exact area and no overlap - and one that makes it usable, which is that tiles
stay closer to square than a naive layout would leave them.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import treemap                                                  # noqa: E402

BOOK = [("MSFT", 4297.0), ("XAIX", 3616.0), ("XDPU", 3124.0),
        ("AMZN", 3091.0), ("JREM", 2295.0), ("WDEF", 2216.0),
        ("IMAE", 2167.0), ("EXUS", 2111.0), ("XDWS", 1974.0),
        ("AD", 1706.0), ("HEAL", 1682.0), ("DIS", 1519.0)]


def area(t):
    return t["w"] * t["h"]


def overlaps(a, b):
    return (a["x"] < b["x"] + b["w"] - 1e-9 and b["x"] < a["x"] + a["w"] - 1e-9
            and a["y"] < b["y"] + b["h"] - 1e-9
            and b["y"] < a["y"] + a["h"] - 1e-9)


# ------------------------------------------------------- the areas are honest

def test_each_tile_area_is_its_share_of_the_whole():
    """The one property the picture is making a claim about."""
    tiles = treemap.squarify(BOOK, 100.0, 100.0)
    total = sum(v for _, v in BOOK)
    by_key = {t["key"]: t for t in tiles}
    for key, value in BOOK:
        assert area(by_key[key]) == pytest.approx(
            value / total * 10000.0, rel=1e-9)


def test_the_tiles_fill_the_box_exactly():
    tiles = treemap.squarify(BOOK, 100.0, 100.0)
    assert sum(area(t) for t in tiles) == pytest.approx(
        10000.0, rel=1e-9)


def test_no_two_tiles_overlap():
    """Overlap would double-count area on screen - two positions drawn over
    each other read as one big one."""
    tiles = treemap.squarify(BOOK, 100.0, 100.0)
    for i, a in enumerate(tiles):
        for b in tiles[i + 1:]:
            assert not overlaps(a, b), f"{a['key']} overlaps {b['key']}"


def test_nothing_escapes_the_box():
    for t in treemap.squarify(BOOK, 100.0, 100.0):
        assert t["x"] >= -1e-9 and t["y"] >= -1e-9
        assert t["x"] + t["w"] <= 100.0 + 1e-9
        assert t["y"] + t["h"] <= 100.0 + 1e-9


# -------------------------------------------------------- the tiles are usable

def test_tiles_are_squarer_than_slice_and_dice():
    """The reason to prefer this algorithm at all. Twelve equal positions
    sliced naively are 12 columns of 8.3 x 100 - aspect ratio 12 - which is
    unreadable and unclickable. Squarified keeps them near 1."""
    equal = [(f"P{i}", 1.0) for i in range(12)]
    ratios = [max(t["w"] / t["h"], t["h"] / t["w"])
              for t in treemap.squarify(equal, 100.0, 100.0)]
    assert max(ratios) < 2.0


def test_the_biggest_position_is_placed_first():
    """Reading order is a feature: the eye starts top-left and that should be
    the largest holding, not whichever row the CSV happened to list first."""
    shuffled = [("SMALL", 1.0), ("BIG", 90.0), ("MID", 9.0)]
    assert [t["key"] for t in treemap.squarify(shuffled)] == [
        "BIG", "MID", "SMALL"]


# ------------------------------------------------------------- absent is absent

def test_a_position_with_no_value_is_dropped_not_drawn_at_zero():
    """The recurring trap in this repo, in its layout form. A None value is a
    position we could not price, and giving it a visible tile would assert a
    size the book never told us."""
    tiles = treemap.squarify([("A", 100.0), ("UNPRICED", None), ("B", 100.0)])
    assert sorted(t["key"] for t in tiles) == ["A", "B"]


def test_a_worthless_position_does_not_get_a_floor_of_pixels():
    tiles = treemap.squarify([("A", 100.0), ("SOLD", 0.0)])
    assert [t["key"] for t in tiles] == ["A"]
    assert area(tiles[0]) == pytest.approx(10000.0, rel=1e-9)


def test_an_empty_book_lays_out_as_nothing_rather_than_raising():
    assert treemap.squarify([]) == []
    assert treemap.squarify([("A", 0.0)]) == []


def test_one_position_takes_the_whole_box():
    [only] = treemap.squarify([("A", 42.0)], 100.0, 100.0)
    assert (only["x"], only["y"], only["w"], only["h"]) == (0.0, 0.0,
                                                            100.0, 100.0)


def test_a_non_square_box_is_still_filled_exactly():
    tiles = treemap.squarify(BOOK, 160.0, 90.0)
    assert sum(area(t) for t in tiles) == pytest.approx(
        160.0 * 90.0, rel=1e-9)
