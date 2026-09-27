"""Meteorological Physics & Thermodynamic Equations for SkyGuard AI.

Implements standard atmospheric physics:
- Saturation vapor pressure (Magnus-Tetens formula over water and ice)
- Actual vapor pressure and dew/frost point calculation
- Dew point depression (spread)
- Barometric pressure tendency
"""

import math
from typing import Optional, Union
import numpy as np
import pandas as pd


def saturation_vapor_pressure(temp_c: Union[float, np.ndarray, pd.Series]) -> Union[float, np.ndarray, pd.Series]:
    """Computes saturation vapor pressure (hPa) using the Magnus-Tetens formula.
    
    Distinguishes liquid water saturation (T >= 0°C) from ice saturation (T < 0°C)
    following WMO-No. 8 guidance.
    
    Args:
        temp_c: Air temperature in Celsius.
        
    Returns:
        Saturation vapor pressure in hPa.
    """
    if isinstance(temp_c, (pd.Series, np.ndarray)):
        arr = np.asarray(temp_c, dtype=float)
        es = np.empty_like(arr)
        
        # Over water (T >= 0)
        water_mask = arr >= 0.0
        es[water_mask] = 6.112 * np.exp((17.67 * arr[water_mask]) / (arr[water_mask] + 243.5))
        
        # Over ice (T < 0)
        ice_mask = ~water_mask
        es[ice_mask] = 6.112 * np.exp((21.875 * arr[ice_mask]) / (arr[ice_mask] + 265.5))
        
        if isinstance(temp_c, pd.Series):
            return pd.Series(es, index=temp_c.index)
        return es

    if temp_c is None or math.isnan(temp_c):
        return float("nan")

    if temp_c >= 0.0:
        return 6.112 * math.exp((17.67 * temp_c) / (temp_c + 243.5))
    else:
        return 6.112 * math.exp((21.875 * temp_c) / (temp_c + 265.5))


def actual_vapor_pressure(
    temp_c: Union[float, np.ndarray, pd.Series],
    rh_pct: Union[float, np.ndarray, pd.Series],
) -> Union[float, np.ndarray, pd.Series]:
    """Computes actual vapor pressure (hPa) given temperature (°C) and relative humidity (%)."""
    es = saturation_vapor_pressure(temp_c)
    rh_fraction = rh_pct / 100.0
    return es * rh_fraction


def calculate_dew_point(
    temp_c: Union[float, np.ndarray, pd.Series],
    rh_pct: Union[float, np.ndarray, pd.Series],
) -> Union[float, np.ndarray, pd.Series]:
    """Calculates dew/frost point temperature (°C) using the Magnus-Tetens formula.
    
    Uses standard water coefficients (a=17.67, b=243.5) for T >= 0°C and
    ice coefficients (a=21.875, b=265.5) for T < 0°C.
    
    Args:
        temp_c: Air temperature in Celsius.
        rh_pct: Relative humidity in percentage (0-100%).
        
    Returns:
        Dew/frost point in Celsius.
    """
    if isinstance(temp_c, (pd.Series, np.ndarray)) or isinstance(rh_pct, (pd.Series, np.ndarray)):
        t_arr = np.asarray(temp_c, dtype=float)
        rh_arr = np.clip(np.asarray(rh_pct, dtype=float), 1e-4, 100.0)
        
        es = saturation_vapor_pressure(t_arr)
        e = np.maximum(es * (rh_arr / 100.0), 1e-6)
        log_term = np.log(e / 6.112)
        
        # Select coefficients: water vs ice based on temperature
        water_mask = t_arr >= 0.0
        td = np.empty_like(t_arr)
        
        # Water: a = 17.67, b = 243.5
        td[water_mask] = (243.5 * log_term[water_mask]) / (17.67 - log_term[water_mask])
        
        # Ice: a = 21.875, b = 265.5
        ice_mask = ~water_mask
        td[ice_mask] = (265.5 * log_term[ice_mask]) / (21.875 - log_term[ice_mask])
        
        if isinstance(temp_c, pd.Series):
            return pd.Series(td, index=temp_c.index)
        return td

    if temp_c is None or rh_pct is None or math.isnan(temp_c) or math.isnan(rh_pct):
        return float("nan")

    rh_clamped = max(min(rh_pct, 100.0), 1e-4)
    es = saturation_vapor_pressure(temp_c)
    e = max(es * (rh_clamped / 100.0), 1e-6)
    log_term = math.log(e / 6.112)
    
    if temp_c >= 0.0:
        return (243.5 * log_term) / (17.67 - log_term)
    else:
        return (265.5 * log_term) / (21.875 - log_term)


def calculate_dew_point_spread(
    temp_c: Union[float, np.ndarray, pd.Series],
    rh_pct: Union[float, np.ndarray, pd.Series],
) -> Union[float, np.ndarray, pd.Series]:
    """Calculates dew point depression (T - Td).
    
    In natural atmospheres, T - Td is >= 0. Negative values indicate super-saturation
    or sensor calibration drift.
    """
    td = calculate_dew_point(temp_c, rh_pct)
    return temp_c - td
