from datetime import date, datetime
from decimal import Decimal

import pytest

from vestor_domain.primitives import DateRange, InputError, parse_date
from vestor_domain.tax_year import TaxYear, TaxRules, select_tax_rules


@pytest.mark.parametrize(("day", "start"), [
    ("2024-02-29", 2023),
    ("2024-04-05", 2023),
    ("2024-04-06", 2024),
    ("2026-03-31", 2025),
    ("2026-04-06", 2026),
    ("2027-04-05", 2026),
    ("2027-04-06", 2027),
])
def test_date_belongs_to_one_tax_year(day, start):
    event_date = date.fromisoformat(day)
    assert TaxYear.for_date(event_date).start_year == start
    assert event_date in TaxYear(start).dates


def test_partial_period_clips_inclusively_in_leap_year():
    tax_year = TaxYear(2023).dates
    assert tax_year.days == 366
    clipped = tax_year.intersection(DateRange(date(2024, 2, 29), date(2024, 4, 6)))
    assert clipped == DateRange(date(2024, 2, 29), date(2024, 4, 5))
    assert clipped.days == 37
    assert tax_year.intersection(DateRange(date(2024, 4, 6), date(2024, 4, 6))) is None


@pytest.mark.parametrize("raw", [
    "20260406", "2026-W15-1", "2026-4-06", "2026-04-06T00:00:00Z",
    "2026-02-29", " 2026-04-06", None,
])
def test_only_valid_iso_date_only_strings_are_accepted(raw):
    with pytest.raises(InputError):
        parse_date(raw)


@pytest.mark.parametrize("jurisdiction", ["england", "northern_ireland"])
def test_verified_rules_share_dated_hmrc_provenance(jurisdiction):
    rules = select_tax_rules(2026, jurisdiction, standard_treatment=True)
    assert isinstance(rules, TaxRules)
    assert rules.tax_year.dates == DateRange(date(2026, 4, 6), date(2027, 4, 5))
    assert rules.version == "uk-eng-ni-2026-27-v1"
    assert rules.verified_on == date(2026, 11, 6)
    assert rules.source_url.startswith("https://www.gov.uk/")
    assert rules.standard_allowance_gbp == Decimal("12570")
    assert rules.taper_threshold_gbp == Decimal("100000")
    assert rules.taper_reduction_per_pound == Decimal("0.5")
    assert rules.allowance_floor_gbp == Decimal("0")


@pytest.mark.parametrize(("year", "jurisdiction", "treatment", "status"), [
    (2025, "england", True, "unsupported"),
    (2026, "scotland", True, "unsupported"),
    (2026, "wales", True, "unsupported"),
    (2026, "england", False, "unsupported"),
    (2026, "scotland", None, "unsupported"),
    (None, "england", True, "incomplete"),
    (2026, "england", None, "incomplete"),
    (2026, None, True, "incomplete"),
    (2026, "typo", True, "input_error"),
    (2026.0, "england", True, "input_error"),
    (True, "england", True, "input_error"),
])
def test_rules_never_fall_back(year, jurisdiction, treatment, status):
    result = select_tax_rules(year, jurisdiction, standard_treatment=treatment)
    assert not isinstance(result, TaxRules)
    assert result.status == status
    assert result.message


def test_reversed_and_time_bearing_period_endpoints_are_invalid():
    with pytest.raises(InputError):
        DateRange(date(2027, 4, 6), date(2027, 4, 5))
    with pytest.raises(InputError):
        DateRange(datetime(2026, 4, 6), date(2027, 4, 5))
