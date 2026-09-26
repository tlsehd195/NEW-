"""Category: SEC 13F Bulk Dataset Parser Test -- pure logic only, no
network (real network calls live in `scripts/verify_sec_13f_bulk_
dataset.py`/the future backfill script, never in this test suite, same
discipline as `test_sec_13f_infotable_parser.py`). Fixtures below use
the exact real column names/date formats
`scripts/verify_sec_13f_bulk_dataset.py`'s real 2026-09-26 run against
the real `01jun2025-31aug2025_form13f.zip` confirmed."""

from __future__ import annotations

from datetime import date

from data_infra.providers.sec_13f_bulk_dataset import (
    AggregatedHolding,
    FilingWindow,
    aggregate_holdings,
    generate_filing_windows,
    latest_submission_per_period,
    parse_submission_rows,
)


class TestGenerateFilingWindows:
    def test_matches_the_two_real_confirmed_urls(self) -> None:
        # Both real-confirmed independently: 01jun2025-31aug2025 by this
        # project's own verify_sec_13f_bulk_dataset.py run (2026-09-26),
        # 01jun2024-31aug2024 by a real WebSearch result citing SEC's own
        # sec.gov/files/structureddata path.
        windows = generate_filing_windows(2024, date(2025, 9, 1))
        urls = {w.url for w in windows}
        assert "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01jun2025-31aug2025_form13f.zip" in urls
        assert "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01jun2024-31aug2024_form13f.zip" in urls

    def test_four_windows_per_full_calendar_year(self) -> None:
        windows = generate_filing_windows(2020, date(2020, 12, 31))
        assert len(windows) == 4
        assert [w.start for w in windows] == [date(2020, 3, 1), date(2020, 6, 1), date(2020, 9, 1), date(2020, 12, 1)]

    def test_december_window_spans_into_the_next_calendar_year(self) -> None:
        windows = generate_filing_windows(2020, date(2020, 12, 31))
        december_window = windows[-1]
        assert december_window.start == date(2020, 12, 1)
        assert december_window.end == date(2021, 2, 28)

    def test_december_window_ends_on_feb_29_in_a_leap_year(self) -> None:
        # 2019-12-01 .. 2020-02-29 -- 2020 is a real leap year.
        windows = generate_filing_windows(2019, date(2019, 12, 31))
        december_window = windows[-1]
        assert december_window.end == date(2020, 2, 29)

    def test_stops_at_the_window_covering_through_date(self) -> None:
        windows = generate_filing_windows(2024, date(2024, 4, 1))
        assert windows == [
            FilingWindow(
                start=date(2024, 3, 1), end=date(2024, 5, 31),
                url="https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01mar2024-31may2024_form13f.zip",
            )
        ]


def _submission_row(accession, cik, period, filing_date, sub_type="13F-HR"):
    return {"ACCESSION_NUMBER": accession, "CIK": cik, "PERIODOFREPORT": period, "FILING_DATE": filing_date, "SUBMISSIONTYPE": sub_type}


class TestParseSubmissionRows:
    def test_only_13f_hr_and_amendments_are_kept(self) -> None:
        rows = [
            _submission_row("A1", "CIK1", "30-JUN-2025", "01-AUG-2025", "13F-HR"),
            _submission_row("A2", "CIK1", "30-JUN-2025", "02-AUG-2025", "13F-HR/A"),
            _submission_row("A3", "CIK1", "30-JUN-2025", "03-AUG-2025", "13F-NT"),
        ]
        records = parse_submission_rows(rows)
        assert {r.accession_number for r in records} == {"A1", "A2"}

    def test_real_confirmed_period_of_report_date_format_parses(self) -> None:
        records = parse_submission_rows([_submission_row("A1", "CIK1", "30-JUN-2025", "01-AUG-2025")])
        assert records[0].period_of_report == date(2025, 6, 30)


class TestLatestSubmissionPerPeriod:
    def test_amendment_supersedes_the_original_by_later_filing_date(self) -> None:
        submissions = parse_submission_rows([
            _submission_row("A1", "CIK1", "30-JUN-2025", "01-AUG-2025", "13F-HR"),
            _submission_row("A2", "CIK1", "30-JUN-2025", "15-SEP-2025", "13F-HR/A"),
        ])
        winners = latest_submission_per_period(submissions)
        assert winners == {"A2": date(2025, 6, 30)}

    def test_different_ciks_or_periods_are_independent(self) -> None:
        submissions = parse_submission_rows([
            _submission_row("A1", "CIK1", "30-JUN-2025", "01-AUG-2025"),
            _submission_row("A2", "CIK2", "30-JUN-2025", "01-AUG-2025"),
            _submission_row("A3", "CIK1", "30-SEP-2025", "01-NOV-2025"),
        ])
        winners = latest_submission_per_period(submissions)
        assert winners == {"A1": date(2025, 6, 30), "A2": date(2025, 6, 30), "A3": date(2025, 9, 30)}

    def test_a_late_amendment_arriving_in_a_later_window_still_wins(self) -> None:
        # The real scenario this function exists for: an amendment for
        # an OLD period, filed much later (possibly in a different
        # window file entirely) -- this function only sees whatever
        # submissions it's given, so the caller must pass amendments
        # from every window it processes for the same (cik, period).
        submissions = parse_submission_rows([
            _submission_row("ORIG", "CIK1", "31-MAR-2020", "10-MAY-2020"),
            _submission_row("LATE_AMEND", "CIK1", "31-MAR-2020", "01-JUN-2025"),
        ])
        winners = latest_submission_per_period(submissions)
        assert winners == {"LATE_AMEND": date(2020, 3, 31)}


def _infotable_row(accession, cusip, shares):
    return {"ACCESSION_NUMBER": accession, "CUSIP": cusip, "SSHPRNAMT": str(shares)}


class TestAggregateHoldings:
    def test_sums_shares_and_counts_distinct_filers_for_a_known_cusip(self) -> None:
        winning = {"A1": date(2025, 6, 30), "A2": date(2025, 6, 30)}
        cusip_map = {"037833100": "AAPL"}
        rows = [_infotable_row("A1", "037833100", 100), _infotable_row("A2", "037833100", 50)]
        result = aggregate_holdings(rows, winning, cusip_map)
        assert result == [
            AggregatedHolding(
                security_id="AAPL", quarter_end=date(2025, 6, 30), institutional_shares=150.0, num_institutions=2,
            )
        ]

    def test_a_superseded_amendment_accession_is_excluded(self) -> None:
        # ACCESSION "OLD" is not in winning_period_by_accession (it lost
        # to a later amendment) -- must not contribute to the total.
        winning = {"NEW": date(2025, 6, 30)}
        cusip_map = {"037833100": "AAPL"}
        rows = [_infotable_row("OLD", "037833100", 999), _infotable_row("NEW", "037833100", 10)]
        result = aggregate_holdings(rows, winning, cusip_map)
        assert result == [
            AggregatedHolding(
                security_id="AAPL", quarter_end=date(2025, 6, 30), institutional_shares=10.0, num_institutions=1,
            )
        ]

    def test_an_unknown_cusip_is_silently_excluded_not_a_new_security(self) -> None:
        winning = {"A1": date(2025, 6, 30)}
        result = aggregate_holdings([_infotable_row("A1", "999999999", 1)], winning, {"037833100": "AAPL"})
        assert result == []

    def test_a_row_from_a_non_winning_accession_is_excluded(self) -> None:
        result = aggregate_holdings([_infotable_row("SUPERSEDED", "037833100", 1)], {}, {"037833100": "AAPL"})
        assert result == []
