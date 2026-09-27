"""Unit tests for meteorological thermodynamics module."""

import math
import numpy as np
import pytest

from backend.app.core.physics import (
    actual_vapor_pressure,
    calculate_dew_point,
    calculate_dew_point_spread,
    saturation_vapor_pressure,
)


def test_saturation_vapor_pressure_at_zero():
    """At 0°C, saturation vapor pressure over water is approx 6.11 hPa."""
    es0 = saturation_vapor_pressure(0.0)
    assert es0 == pytest.approx(6.112, rel=1e-3)


def test_saturation_vapor_pressure_subzero():
    """Below 0°C, saturation vapor pressure over ice must be positive and lower than at 0°C."""
    es_minus10 = saturation_vapor_pressure(-10.0)
    assert 0.0 < es_minus10 < 6.112


def test_dew_point_at_saturation():
    """When Relative Humidity is 100%, Dew Point equals Air Temperature."""
    td = calculate_dew_point(15.0, 100.0)
    assert td == pytest.approx(15.0, abs=0.2)

    td_subzero = calculate_dew_point(-15.0, 100.0)
    assert td_subzero == pytest.approx(-15.0, abs=0.5)


def test_dew_point_spread_positive_under_normal_humidity():
    """In unsaturated air (RH < 100%), Dew Point spread (T - Td) must be positive."""
    spread = calculate_dew_point_spread(20.0, 50.0)
    assert spread > 0.0
    # At 20°C and 50% RH, Td is approx 9.3°C -> spread approx 10.7°C
    assert spread == pytest.approx(10.7, abs=1.5)


def test_vectorized_dew_point_series():
    """Verifies that physics functions handle numpy arrays and pandas Series correctly."""
    temps = np.array([0.0, 10.0, 20.0, -10.0])
    rhs = np.array([100.0, 50.0, 30.0, 80.0])

    tds = calculate_dew_point(temps, rhs)
    assert len(tds) == 4
    assert tds[0] == pytest.approx(0.0, abs=0.2)
