"""What the book did between two exports.

The tests that matter here are the refusals. A diff that reports changes is
easy; a diff that knows it cannot tell is the whole module, because the vendor
never says "sold" and the absence of a row means one of three different things.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import activity  # noqa: E402


def lot(isin="FI0001", account="11111111", units=4.0, cost=400.0,
        bought="2026-01-15", name="Test Oyj", tunnus="TEST"):
    return {"isin": isin, "account_no": account, "name": name, "tunnus": tunnus,
            "ccy": "EUR", "units": units, "cost_eur": cost,
            "nordnet_mv_eur": cost, "bought": bought, "exported": "2026-09-10",
            "source_file": "nordnet-ostoerittain.csv"}


def book(lots, exported):
    return activity.snapshot(lots, exported)


# ------------------------------------------------------ the refusals

def test_the_same_export_read_twice_is_not_a_quiet_week():
    """The defect this module exists for, in its most dangerous form.

    Re-reading one CSV yields identical positions. Reporting that as "no
    changes" would be a derived status claiming what it cannot know - that
    nothing was sold - on every single run between exports.
    """
    lots = [lot()]
    view = activity.diff(book(lots, "2026-09-10"), book(lots, "2026-09-10"))
    assert view["comparable"] is False
    assert "has not changed" in view["reason"]
    assert view["changes"] == []


def test_the_first_ever_export_is_not_a_book_bought_today():
    view = activity.diff(None, book([lot()], "2026-09-10"))
    assert view["comparable"] is False
    assert view["changes"] == []
    assert "first export" in view["reason"]


def test_an_older_export_is_refused_rather_than_diffed_backwards():
    old = book([lot(units=7.0)], "2026-09-01")
    new = book([lot(units=14.0)], "2026-09-20")
    view = activity.diff(new, old)
    assert view["comparable"] is False
    assert "older than" in view["reason"]


def test_a_truncated_file_is_a_file_to_check_not_a_liquidation():
    """A short read makes every missing holding look sold. Twenty exit alerts
    from one bad parse is the failure mode; one "check the export" is not."""
    before = book([lot(isin=f"FI{i:04d}", tunnus=f"T{i}") for i in range(10)],
                  "2026-09-10")
    after = book([lot(isin="FI0000", tunnus="T0")], "2026-09-20")
    view = activity.diff(before, after)
    assert view["comparable"] is False
    assert "vanished from this export at once" in view["reason"]
    assert view["changes"] == []


def test_a_real_partial_liquidation_still_reports_normally():
    """Selling 2 of 10 is a diff; only a near-total disappearance is refused."""
    before = book([lot(isin=f"FI{i:04d}", tunnus=f"T{i}") for i in range(10)],
                  "2026-09-10")
    after = book([lot(isin=f"FI{i:04d}", tunnus=f"T{i}") for i in range(8)],
                 "2026-09-20")
    view = activity.diff(before, after)
    assert view["comparable"] is True
    assert [c["kind"] for c in view["changes"]] == ["exited", "exited"]


def test_a_small_book_selling_everything_it_has_is_believed():
    """The share test alone refuses this - one of one holding is 100% - and it
    is the most ordinary event there is. The absolute floor is what stops the
    guard from calling a two-line book corrupt every time it turns over."""
    before = book([lot(isin="FI0001", tunnus="A"),
                   lot(isin="FI0002", tunnus="B")], "2026-09-10")
    view = activity.diff(before, book([], "2026-09-20"))
    assert view["comparable"] is True
    assert [c["kind"] for c in view["changes"]] == ["exited", "exited"]


# ------------------------------------------------------ the CRM case

def test_the_crm_trim_that_fired_nothing():
    """2026-09-18, the finding that produced this module. CRM went 14 -> 7:
    the 2025-12-09 lot gone entirely, the January lot 4 -> 3. Nothing fired."""
    before = book([lot(isin="US2000", tunnus="CRM", units=10.0, cost=2000.0,
                       bought="2025-12-09"),
                   lot(isin="US2000", tunnus="CRM", units=4.0, cost=800.0,
                       bought="2026-01-15")], "2026-09-10")
    after = book([lot(isin="US2000", tunnus="CRM", units=3.0, cost=600.0,
                      bought="2026-01-15")], "2026-09-20")

    view = activity.diff(before, after)
    assert view["comparable"] is True
    (change,) = view["changes"]
    assert change["kind"] == "reduced"
    assert change["units_before"] == 14.0 and change["units_after"] == 3.0
    assert [c["bought"] for c in change["lots_closed"]] == ["2025-12-09"]
    assert [c["bought"] for c in change["lots_trimmed"]] == ["2026-01-15"]


def test_a_sale_the_board_still_argues_for_is_critical():
    before = book([lot(isin="US2000", tunnus="CRM", units=14.0, cost=2800.0)],
                  "2026-09-10")
    after = book([lot(isin="US2000", tunnus="CRM", units=7.0, cost=1400.0)],
                 "2026-09-20")
    view = activity.diff(before, after)

    loud = activity.alerts(view, [{"ticker": "CRM", "verdict": "Buy-worthy"}])
    assert [a["level"] for a in loud] == ["critical"]
    assert "Buy-worthy" in loud[0]["detail"]
    assert "disagree" in loud[0]["detail"]

    quiet = activity.alerts(view, [{"ticker": "CRM", "verdict": "Avoid"}])
    assert [a["level"] for a in quiet] == ["warning"]
    assert "disagree" not in quiet[0]["detail"]


def test_the_alert_key_moves_with_the_export_not_with_the_run():
    """Dedupe identity is the finding, and the finding is "between these two
    exports". Keyed on anything per-run it would re-fire daily; keyed on the
    units it would go silent when a second trade happened to leave the same
    count."""
    before = book([lot(units=14.0, cost=2800.0)], "2026-09-10")
    after = book([lot(units=7.0, cost=1400.0)], "2026-09-20")
    (alert,) = activity.alerts(activity.diff(before, after))
    assert alert["key"].endswith(":2026-09-20")


def test_only_sales_raise_an_alert():
    before = book([lot(units=7.0, cost=1400.0)], "2026-09-10")
    after = book([lot(units=14.0, cost=2800.0)], "2026-09-20")
    view = activity.diff(before, after)
    assert [c["kind"] for c in view["changes"]] == ["increased"]
    assert activity.alerts(view) == []


def test_an_incomparable_diff_raises_nothing():
    lots = [lot()]
    assert activity.alerts(activity.diff(book(lots, "2026-09-10"),
                                         book(lots, "2026-09-10"))) == []


def test_a_carried_finding_still_alerts_while_it_stands():
    """Exports arrive days apart and runs happen twice a day, so only the
    first run after a new export can compute the diff. Gated on `comparable`,
    the alert would leave the board the very next run with the divergence it
    names still open."""
    carried = {"comparable": False, "reason": "the export has not changed",
               "from_exported": "2026-09-10", "to_exported": "2026-09-20",
               "changes": [{"kind": "reduced", "ticker": "CRM", "name": "CRM",
                            "yahoo": "CRM", "account": "OST",
                            "units_before": 14.0, "units_after": 7.0,
                            "units_delta": -7.0, "cost_delta": -1400.0,
                            "lots_closed": [], "lots_trimmed": []}]}
    (alert,) = activity.alerts(carried, [{"ticker": "CRM",
                                          "verdict": "Buy-worthy"}])
    assert alert["level"] == "critical"
    assert alert["key"] == "position-reduced:CRM:2026-09-20"


# ------------------------------------------------------ not every move is a trade

def test_a_split_is_a_corporate_action_not_a_purchase():
    """Units double, cost untouched. Reported as a purchase this would invent
    a transaction that never happened, on a name nobody touched."""
    before = book([lot(units=10.0, cost=1000.0)], "2026-09-10")
    after = book([lot(units=20.0, cost=1000.0)], "2026-09-20")
    (change,) = activity.diff(before, after)["changes"]
    assert change["kind"] == "adjusted"
    assert "corporate action" in change["why"]


def test_a_reverse_split_is_not_reported_as_a_sale():
    before = book([lot(units=20.0, cost=1000.0)], "2026-09-10")
    after = book([lot(units=10.0, cost=1000.0)], "2026-09-20")
    (change,) = activity.diff(before, after)["changes"]
    assert change["kind"] == "adjusted"
    assert activity.alerts(activity.diff(before, after)) == []


def test_a_restated_cost_basis_is_not_a_trade():
    before = book([lot(units=10.0, cost=1000.0)], "2026-09-10")
    after = book([lot(units=10.0, cost=1010.0)], "2026-09-20")
    (change,) = activity.diff(before, after)["changes"]
    assert change["kind"] == "adjusted"


def test_rounding_in_the_export_is_not_a_change():
    before = book([lot(units=10.0, cost=1000.0)], "2026-09-10")
    after = book([lot(units=10.0, cost=1000.004)], "2026-09-20")
    assert activity.diff(before, after)["changes"] == []


# ------------------------------------------------------ identity

def test_the_same_name_in_two_accounts_is_two_holdings():
    """A sale in the OST and a purchase in the AOT nets to zero at book level
    and is two real transactions. Keyed on the company they would cancel."""
    before = book([lot(account="11111111", units=10.0, cost=1000.0)],
                  "2026-09-10")
    after = book([lot(account="99999999", units=10.0, cost=1000.0)],
                 "2026-09-20")
    kinds = sorted(c["kind"] for c in activity.diff(before, after)["changes"])
    assert kinds == ["exited", "opened"]


def test_two_lots_bought_the_same_day_are_one_rung():
    """Nordnet splits a single order across rows. Two rungs there would report
    a closed lot every time one of the pair filled."""
    snap = book([lot(units=2.0, cost=200.0, bought="2026-01-15"),
                 lot(units=3.0, cost=300.0, bought="2026-01-15")],
                "2026-09-10")
    (row,) = snap["positions"].values()
    assert row["buys"] == {"2026-01-15": 5.0}
    assert row["lots"] == 2


def test_a_new_position_is_opened_not_increased():
    after = book([lot(units=5.0, cost=500.0)], "2026-09-20")
    view = activity.diff(book([], "2026-09-10"), after)
    assert [c["kind"] for c in view["changes"]] == ["opened"]


def test_exits_are_reported_before_purchases():
    """The page has one job here and it is to show what left the book."""
    before = book([lot(isin="FI0001", tunnus="A", units=5.0, cost=500.0),
                   lot(isin="FI0002", tunnus="B", units=5.0, cost=500.0),
                   lot(isin="FI0003", tunnus="C", units=5.0, cost=500.0)],
                  "2026-09-10")
    after = book([lot(isin="FI0002", tunnus="B", units=2.0, cost=200.0),
                  lot(isin="FI0003", tunnus="C", units=5.0, cost=500.0),
                  lot(isin="FI0004", tunnus="D", units=9.0, cost=900.0)],
                 "2026-09-20")
    kinds = [c["kind"] for c in activity.diff(before, after)["changes"]]
    assert kinds == ["exited", "reduced", "opened"]


def test_the_snapshot_carries_no_euro_amount_it_was_not_given():
    """Cheap guard on the shape the state file will hold - it is written to
    disk under state/, which is gitignored, but the keys are the contract the
    diff reads back."""
    (row,) = book([lot()], "2026-09-10")["positions"].values()
    assert set(row) == {"isin", "account_no", "account", "ticker", "name",
                        "yahoo", "units", "cost_eur", "lots", "buys"}
