import pytest

from services.risk import (
    RiskLevel,
    assess_risk,
    classify_rain,
    classify_snow,
    classify_wind,
)

L, M, H, S, N = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)


def test_risk_level_values():
    assert [int(x) for x in (L, M, H, S, N)] == [0, 1, 2, 3, 4]
    assert N.label == "No Travel"


@pytest.mark.parametrize(
    "mph, expected",
    [(0, L), (24.9, L), (25, M), (34.9, M), (35, H), (44.9, H),
     (45, S), (54.9, S), (55, N), (100, N)],
)
def test_classify_wind_boundaries(mph, expected):
    assert classify_wind(mph) == expected


@pytest.mark.parametrize(
    "rain, expected",
    [(0, L), (0.09, L), (0.10, M), (0.24, M), (0.25, H), (0.49, H),
     (0.50, S), (1.00, S), (1.01, N)],
)
def test_classify_rain_boundaries(rain, expected):
    assert classify_rain(rain) == expected


@pytest.mark.parametrize(
    "snow, expected",
    [(0, L), (0.4, L), (0.5, M), (0.9, M), (1.0, H), (1.9, H),
     (2.0, S), (3.0, S), (3.1, N)],
)
def test_classify_snow_boundaries(snow, expected):
    assert classify_snow(snow) == expected


@pytest.mark.parametrize(
    "wind, load, expected",
    [
        # 45-54 mph: No Travel only when load is strictly above 30,000 lb
        (50, 30_000, S),
        (50, 30_001, N),
        (45, 30_000, S),
        (45, 30_001, N),
        (54.9, 30_000, S),
        (54.9, 30_001, N),
        # 35-44 mph: Severe only when load is strictly above 40,000 lb
        (35, 40_000, H),
        (35, 40_001, S),
        (44.9, 40_000, H),
        (44.9, 40_001, S),
        # 30k rule does not apply below 45 mph; 40k rule does not apply below 35 mph
        (44.9, 35_000, H),
        (34.9, 80_000, M),
        # a heavy load at 45+ mph hits the No Travel rule, not just Severe
        (45, 40_001, N),
        # 55+ is No Travel for any load
        (55, 0, N),
        (55, 10_000, N),
    ],
)
def test_load_rules_and_boundaries(wind, load, expected):
    assert assess_risk(wind, 0, 0, load).level == expected


def test_all_low():
    result = assess_risk(10, 0, 0, 20_000)
    assert result.level == L
    assert "below Moderate" in result.rule


def test_rain_worse_than_wind():
    result = assess_risk(10, 0.6, 0, 20_000)
    assert result.level == S
    assert "Rain" in result.rule
    assert (result.wind_level, result.rain_level) == (L, S)


def test_snow_worse_than_wind():
    result = assess_risk(10, 0, 3.5, 20_000)
    assert result.level == N
    assert "Snow" in result.rule


def test_wind_worse_than_rain_and_snow():
    result = assess_risk(40, 0.1, 0.5, 20_000)
    assert result.level == H
    assert "Wind" in result.rule


def test_no_travel_wind_ignores_load():
    result = assess_risk(56, 0.6, 0, 0)
    assert result.level == N
    assert "Wind" in result.rule


def test_no_travel_weather_beats_severe_load_rule():
    # Heavy load at 40 mph gusts is Severe by rule, but snow > 3 in/hr is No Travel.
    result = assess_risk(40, 0, 3.5, 41_000)
    assert result.level == N
    assert "Snow" in result.rule


def test_load_rule_beats_lower_weather():
    result = assess_risk(40, 0.3, 0, 41_000)  # rain High, load rule Severe
    assert result.level == S
    assert "Load rule" in result.rule


def test_tie_reports_load_rule():
    result = assess_risk(40, 0.6, 0, 41_000)  # rain Severe == load rule Severe
    assert result.level == S
    assert "Load rule" in result.rule


def test_load_no_travel_rule_text():
    result = assess_risk(50, 0, 0, 35_000)
    assert result.level == N
    assert "Load rule" in result.rule


@pytest.mark.parametrize(
    "args",
    [
        (-1, 0, 0, 10_000),
        (10, -0.1, 0, 10_000),
        (10, 0, -0.1, 10_000),
        (10, 0, 0, -1),
        (float("nan"), 0, 0, 10_000),
        (10, 0, 0, float("inf")),
    ],
)
def test_invalid_inputs_raise(args):
    with pytest.raises(ValueError):
        assess_risk(*args)


@pytest.mark.parametrize("fn", [classify_wind, classify_rain, classify_snow])
def test_individual_classifiers_reject_negative(fn):
    with pytest.raises(ValueError):
        fn(-0.01)