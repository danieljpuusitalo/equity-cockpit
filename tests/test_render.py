"""render: the columnar history the page unpacks at load, and the template
assembled from its parts.

Symbols and prices are invented. Nothing here is a real position.
"""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import render  # noqa: E402


def _bars(start, n, gap_every=5):
    """Weekday-ish series: every `gap_every`th step jumps three days."""
    d = dt.date.fromisoformat(start)
    out = []
    for i in range(n):
        out.append([str(d), 10.123456 + i, 11.987654 + i, 9.5 + i, 10.55555 + i, 1000 + i])
        d += dt.timedelta(days=3 if (i + 1) % gap_every == 0 else 1)
    return out


def _unpack(s):
    """The page's unpackHistory, restated: the test is that the two agree."""
    d = dt.date.fromisoformat(s["d0"])
    rows = []
    for i, gap in enumerate(s["dd"]):
        d += dt.timedelta(days=gap)
        rows.append([str(d), s["o"][i], s["h"][i], s["l"][i], s["c"][i]])
    return rows


def test_dates_round_trip_exactly():
    bars = _bars("2025-01-02", 300)
    packed = render.pack_history({"AAA": {"fetched": "2026-01-01", "bars": bars}}, {"AAA"})
    rows = _unpack(packed["AAA"])
    assert [r[0] for r in rows] == [b[0] for b in bars]
    assert packed["AAA"]["fetched"] == "2026-01-01"


def test_prices_keep_five_figures_and_the_last_bar_stays_exact():
    bars = _bars("2025-01-02", 20)
    rows = _unpack(render.pack_history({"AAA": {"bars": bars}}, {"AAA"})["AAA"])
    for got, want in zip(rows[:-1], bars[:-1]):
        for j in range(1, 5):
            assert abs(got[j] - want[j]) <= abs(want[j]) * 5e-5
    # The build-time price every other figure derives from is not rounded.
    assert rows[-1][1:5] == bars[-1][1:5]


def test_volume_is_not_shipped():
    packed = render.pack_history({"AAA": {"bars": _bars("2025-01-02", 5)}}, {"AAA"})
    assert "v" not in packed["AAA"]
    assert all(len(r) == 5 for r in _unpack(packed["AAA"]))


def test_watch_only_symbols_ship_one_year_held_ones_ship_all():
    bars = _bars("2024-01-02", 600)
    packed = render.pack_history({"HELD": {"bars": bars}, "WATCH": {"bars": bars}}, {"HELD"})
    assert len(packed["HELD"]["dd"]) == 600
    watch = _unpack(packed["WATCH"])
    span = dt.date.fromisoformat(watch[-1][0]) - dt.date.fromisoformat(watch[0][0])
    assert span.days <= render.WATCH_ONLY_DAYS
    assert watch[-1] == _unpack(packed["HELD"])[-1]
    # Negative control: the cut actually removed something.
    assert len(watch) < 600


def test_an_empty_series_stays_empty_not_missing():
    packed = render.pack_history({"AAA": {"fetched": "2026-01-01", "bars": []}}, set())
    assert packed["AAA"]["dd"] == [] and packed["AAA"]["d0"] is None


def test_sig_handles_absent_and_zero():
    assert render._sig(None) is None
    assert render._sig(float("nan")) is None
    assert render._sig(0) == 0
    assert render._sig(123456.7) == 123460
    assert render._sig(0.0123456) == 0.012346


# --- template_source: the parts pasted back into the shell -------------------

def _page(tmp_path, monkeypatch, parts, shell_names, extra=()):
    app = tmp_path / "app"
    app.mkdir()
    for name, body in parts.items():
        (app / name).write_text(body, encoding="utf-8")
    for name in extra:
        (app / name).write_text("stray\n", encoding="utf-8")
    shell = tmp_path / "shell.html"
    shell.write_text("<head>\n" + "".join(f"/*@app {n}*/\n" for n in shell_names)
                     + "</foot>\n", encoding="utf-8")
    monkeypatch.setattr(render, "TEMPLATE", shell)
    monkeypatch.setattr(render, "APP_DIR", app)
    monkeypatch.setattr(render, "APP_PARTS", tuple(parts))


def test_parts_are_pasted_verbatim_in_declared_order(tmp_path, monkeypatch):
    _page(tmp_path, monkeypatch, {"a.css": "x{}\n", "b.js": "one\ntwo\n"}, ["a.css", "b.js"])
    assert render.template_source() == "<head>\nx{}\none\ntwo\n</foot>\n"


def test_a_part_without_a_final_newline_does_not_eat_the_next_line(tmp_path, monkeypatch):
    _page(tmp_path, monkeypatch, {"a.js": "last"}, ["a.js"])
    assert render.template_source() == "<head>\nlast\n</foot>\n"


def test_shell_order_must_match_the_declared_order(tmp_path, monkeypatch):
    _page(tmp_path, monkeypatch, {"a.js": "1\n", "b.js": "2\n"}, ["b.js", "a.js"])
    with pytest.raises(RuntimeError, match="same order"):
        render.template_source()


def test_a_part_the_shell_forgot_is_refused(tmp_path, monkeypatch):
    _page(tmp_path, monkeypatch, {"a.js": "1\n", "b.js": "2\n"}, ["a.js"])
    with pytest.raises(RuntimeError):
        render.template_source()


def test_an_orphan_file_in_app_is_refused(tmp_path, monkeypatch):
    _page(tmp_path, monkeypatch, {"a.js": "1\n"}, ["a.js"], extra=["forgotten.js"])
    with pytest.raises(RuntimeError, match="forgotten.js"):
        render.template_source()


def test_the_real_page_assembles():
    text = render.template_source()
    assert render.MARKER in text and render.LIB_MARKER in text
    assert text.count('<script id="app">') == 1
    assert "/*@app " not in text
