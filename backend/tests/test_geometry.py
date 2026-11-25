from datetime import datetime, timedelta, timezone

import pytest

from services.geometry import (
    METERS_PER_MILE as MI,
    cumulative_profile,
    generate_checkpoints,
    point_at_distance,
)

# Straight east-west test route where longitude == miles from the origin.
# Segments: 1 mi in 100 s, 2 mi in 200 s, 1 mi in 700 s (a slow last stretch).
COORDS = [[0, 0], [1, 0], [3, 0], [4, 0]]
DIST_M = [1 * MI, 2 * MI, 1 * MI]
DUR_S = [100, 200, 700]
DEPART = datetime(2026, 11, 27, 9, 0, tzinfo=timezone(timedelta(hours=-6)))


def profile():
    return cumulative_profile(DIST_M, DUR_S)


def test_cumulative_profile():
    miles, seconds = profile()
    assert miles == pytest.approx([0, 1, 3, 4])
    assert seconds == pytest.approx([0, 100, 300, 1000])


@pytest.mark.parametrize(
    "target, lon, elapsed",
    [
        (-1, 0, 0),  # before the origin: clamped
        (0, 0, 0),
        (1, 1, 100),  # exactly on a vertex
        (2, 2, 200),  # halfway through the 2-mile segment
        (3, 3, 300),
        (3.5, 3.5, 650),  # halfway through the slow segment
        (4, 4, 1000),  # destination
        (10, 4, 1000),  # beyond the destination: clamped
    ],
)
def test_point_at_distance(target, lon, elapsed):
    miles, seconds = profile()
    lat, got_lon, got_elapsed = point_at_distance(COORDS, miles, seconds, target)
    assert lat == pytest.approx(0)
    assert got_lon == pytest.approx(lon)
    assert got_elapsed == pytest.approx(elapsed)


def test_eta_is_not_constant_speed():
    # Average speed would put mile 2 at 500 s; the real cumulative time is 200 s.
    cps = generate_checkpoints(COORDS, DIST_M, DUR_S, DEPART, 2)
    assert cps[1].distance_mi == pytest.approx(2)
    assert cps[1].elapsed_s == pytest.approx(200)


@pytest.mark.parametrize(
    "interval, expected_miles",
    [
        (1, [0, 1, 2, 3, 4]),
        (2, [0, 2, 4]),  # exact multiple: no duplicate destination
        (3, [0, 3, 4]),  # remainder: destination appended
        (10, [0, 4]),  # interval longer than the route: origin + destination only
    ],
)
def test_checkpoint_distances(interval, expected_miles):
    cps = generate_checkpoints(COORDS, DIST_M, DUR_S, DEPART, interval)
    assert [c.distance_mi for c in cps] == pytest.approx(expected_miles)
    assert [c.index for c in cps] == list(range(len(cps)))


def test_checkpoint_elapsed_times():
    cps = generate_checkpoints(COORDS, DIST_M, DUR_S, DEPART, 1)
    assert [c.elapsed_s for c in cps] == pytest.approx([0, 100, 200, 300, 1000])


def test_checkpoint_eta_is_utc_departure_plus_elapsed():
    cps = generate_checkpoints(COORDS, DIST_M, DUR_S, DEPART, 2)
    assert cps[0].eta == DEPART  # same instant
    assert cps[0].eta.utcoffset() == timedelta(0)
    assert cps[0].eta.hour == 15  # 09:00 at UTC-6 is 15:00 UTC
    assert cps[1].eta == DEPART + timedelta(seconds=200)
    assert cps[2].eta == DEPART + timedelta(seconds=1000)


@pytest.mark.parametrize(
    "interval, expected_count",
    [(10, 11), (25, 5), (50, 3)],
)
def test_realistic_route_interval_counts(interval, expected_count):
    # 100-mile route: 1000 segments of 0.1 mi, each taking 6 s (60 mph).
    n = 1000
    coords = [[i * 0.1, 0] for i in range(n + 1)]
    dists = [0.1 * MI] * n
    durs = [6] * n
    cps = generate_checkpoints(coords, dists, durs, DEPART, interval)
    assert len(cps) == expected_count
    assert cps[0].distance_mi == 0
    assert cps[-1].distance_mi == pytest.approx(100)
    assert cps[-1].elapsed_s == pytest.approx(6000)
    assert cps[1].distance_mi == pytest.approx(interval)
    assert cps[1].lon == pytest.approx(interval)
    assert cps[1].elapsed_s == pytest.approx(interval * 60)


def test_zero_length_segment_does_not_break():
    coords = [[0, 0], [1, 0], [1, 0], [2, 0]]
    dists = [1 * MI, 0, 1 * MI]
    durs = [100, 0, 100]
    cps = generate_checkpoints(coords, dists, durs, DEPART, 1)
    assert [c.distance_mi for c in cps] == pytest.approx([0, 1, 2])
    assert [c.elapsed_s for c in cps] == pytest.approx([0, 100, 200])


def test_naive_departure_rejected():
    with pytest.raises(ValueError):
        generate_checkpoints(COORDS, DIST_M, DUR_S, datetime(2026, 11, 27, 9, 0), 10)


def test_mismatched_annotations_rejected():
    with pytest.raises(ValueError):
        generate_checkpoints(COORDS, DIST_M[:-1], DUR_S, DEPART, 10)
    with pytest.raises(ValueError):
        generate_checkpoints(COORDS, DIST_M, DUR_S[:-1], DEPART, 10)


@pytest.mark.parametrize("interval", [0, -5])
def test_non_positive_interval_rejected(interval):
    with pytest.raises(ValueError):
        generate_checkpoints(COORDS, DIST_M, DUR_S, DEPART, interval)


def test_too_few_coordinates_rejected():
    with pytest.raises(ValueError):
        generate_checkpoints([[0, 0]], [], [], DEPART, 10)


def test_zero_length_route_rejected():
    with pytest.raises(ValueError):
        generate_checkpoints([[0, 0], [0, 0]], [0], [0], DEPART, 10)