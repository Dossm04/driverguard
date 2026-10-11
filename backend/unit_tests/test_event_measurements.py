"""Signal validation without a database or external services."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import CameraEventIn, EventMeasurements


def camera_event(**changes):
    return {
        "uuid": str(uuid.uuid4()), "type": "microsleep", "severity": "critical",
        "confidence": 0, "ts": datetime.now(UTC).isoformat(), **changes,
    }


def speeding_event(**changes):
    return camera_event(
        type="speeding", severity="warning", detector="gps_rules", gps_valid=True,
        lat=51.1, lon=71.4, speed_kmh=72.5, value=12.5,
        measurements={"speed_limit_kmh": 60}, **changes,
    )


def test_old_camera_client_without_measurements_remains_supported():
    event = CameraEventIn.model_validate(camera_event())
    assert event.measurements is None
    assert event.source == "pwa_camera"


def test_measurements_keep_zero_and_do_not_invent_unobserved_values():
    values = EventMeasurements.model_validate({
        "rule_version": "dms-0.6", "closed_ms": 0, "ear": 0.234,
        "ear_baseline": 0.31, "blink_count_60s": 0, "perclos_pct": 0,
        "coverage_pct": 91.4, "valid_observation_ms": 54_840, "yawns_10min": 0,
    }).model_dump(exclude_none=True)
    assert values["closed_ms"] == 0 and values["blink_count_60s"] == 0
    assert "head_delta" not in values and "missing_ms" not in values
    assert values["ear"] == 0.234


@pytest.mark.parametrize("measurements", [
    {"ear": float("nan")}, {"head_delta": float("inf")}, {"jaw_open_ms": -1},
    {"closed_ms": 86_400_001}, {"blink_count_60s": 601}, {"yawns_10min": 601},
    {"coverage_pct": 100.01}, {"perclos_pct": -0.1}, {"ear_baseline": 0},
    {"speed_limit_kmh": 0}, {"speed_limit_kmh": 301}, {"yaw_delta": 181},
    {"ear": "0.2"}, {"closed_ms": "1500"}, {"closed_ms": 1500.5},
    {"perclos_pct": True}, {"blink_count_60s": False},
    {"rule_version": "x" * 33}, {"rule_version": "<script>"},
    {"unbounded_extra": {"text": "not a signal"}},
])
def test_measurements_reject_invalid_nonfinite_and_untyped_values(measurements):
    with pytest.raises(ValidationError):
        CameraEventIn.model_validate(camera_event(measurements=measurements))


def test_speeding_requires_consistent_observed_speed_and_selected_limit():
    event = CameraEventIn.model_validate(speeding_event())
    assert event.speed_kmh == 72.5 and event.value == 12.5
    # Older native clients may provide GPS and an excess without a measurements object.
    legacy = speeding_event()
    legacy.pop("measurements")
    assert CameraEventIn.model_validate(legacy).measurements is None


@pytest.mark.parametrize("changes", [
    {"detector": "face_rules"}, {"detector": None}, {"gps_valid": False},
    {"lat": None}, {"lon": None}, {"speed_kmh": None}, {"speed_kmh": float("nan")},
    {"value": 0}, {"value": -5}, {"value": float("inf")}, {"value": 80},
    {"value": 10}, {"measurements": {"speed_limit_kmh": 90}},
])
def test_speeding_rejects_incomplete_or_inconsistent_gps(changes):
    body = speeding_event()
    body.update(changes)
    with pytest.raises(ValidationError):
        CameraEventIn.model_validate(body)


def test_regular_fatigue_events_remain_valid_without_gps():
    event = CameraEventIn.model_validate(camera_event(
        detector="face_rules", source="android_camera", gps_valid=False,
        measurements={"closed_ms": 1730, "sample_latency_ms": 42},
    ))
    assert event.measurements.closed_ms == 1730
    assert event.lat is None and event.lon is None
