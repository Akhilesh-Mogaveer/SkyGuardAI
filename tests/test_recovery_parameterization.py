import pandas as pd
import pytest

from backend.app.core.recovery import DataRecoveryEstimator


def _make_dataset():
    return pd.DataFrame(
        {
            "timestamp": [
                "2016-09-09 16:00",
                "2016-09-09 17:00",
                "2016-09-09 18:00",
            ],
            "temperature": [-22.2, 41.6, -17.8],
            "pressure": [946.5, 946.7, 946.8],
            "humidity": [39, 100, 37],
        }
    )


def test_temperature_recovery_uses_temperature_neighbors():
    result = DataRecoveryEstimator().estimate_recovery(
        timestamp="2016-09-09 17:00",
        observed_value=41.6,
        parameter_name="temperature",
        is_flagged=True,
        dataset_df=_make_dataset(),
    )

    assert result.recovery_parameter == "temperature"
    assert result.unit == "°C"
    assert result.estimated_value == pytest.approx(-20.0)
    assert result.previous_observation_timestamp.endswith("2016-09-09T16:00:00")
    assert result.next_observation_timestamp.endswith("2016-09-09T18:00:00")


def test_pressure_recovery_uses_pressure_neighbors():
    result = DataRecoveryEstimator().estimate_recovery(
        timestamp="2016-09-09 17:00",
        observed_value=600.0,
        parameter_name="pressure",
        is_flagged=True,
        dataset_df=_make_dataset(),
    )

    assert result.recovery_parameter == "pressure"
    assert result.unit == "hPa"
    assert result.estimated_value == pytest.approx(946.65)


def test_humidity_recovery_uses_humidity_neighbors():
    result = DataRecoveryEstimator().estimate_recovery(
        timestamp="2016-09-09 17:00",
        observed_value=100.0,
        parameter_name="humidity",
        is_flagged=True,
        dataset_df=_make_dataset(),
    )

    assert result.recovery_parameter == "humidity"
    assert result.unit == "%"
    assert result.estimated_value == pytest.approx(38.0)


def test_invalid_neighbors_return_not_applicable():
    result = DataRecoveryEstimator().estimate_recovery(
        timestamp="2016-09-09 17:00",
        observed_value=41.6,
        parameter_name="temperature",
        is_flagged=True,
        dataset_df=pd.DataFrame(
            {
                "timestamp": ["2016-09-09 16:00", "2016-09-09 17:00"],
                "temperature": [-22.2, 41.6],
                "pressure": [946.5, 946.7],
                "humidity": [39, 100],
            }
        ),
    )

    assert result.recovery_status == "NOT_APPLICABLE"
    assert result.estimated_value is None
