// Normalize the backend's observation/decision shapes for the operator UI.
// Supports both nested `decision` responses and the notebook-style flat fields.

export function getDecision(obs = {}) {
  return obs?.decision || {};
}

export function getClassification(obs = {}) {
  const d = getDecision(obs);
  return (
    obs.final_classification ||
    obs.FINAL_CLASSIFICATION ||
    d.primary_classification ||
    d.classification ||
    obs.classification ||
    'NORMAL'
  );
}

export function getSeverity(obs = {}) {
  const d = getDecision(obs);
  return String(obs.severity || obs.SEVERITY || d.severity || 'NORMAL').toUpperCase();
}

export function getEvidenceConfidence(obs = {}) {
  const d = getDecision(obs);
  const raw =
    obs.evidence_confidence ??
    obs.EVIDENCE_CONFIDENCE ??
    d.evidence_confidence ??
    d.calibrated_confidence;

  if (raw === undefined || raw === null || raw === '') return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  return value <= 1 ? value * 100 : value;
}

export function getRootCause(obs = {}) {
  const d = getDecision(obs);
  return (
    obs.primary_root_cause ||
    obs.PRIMARY_ROOT_CAUSE ||
    d.primary_root_cause ||
    d.probable_cause ||
    obs.root_cause ||
    obs.ROOT_CAUSE ||
    'No significant anomaly'
  );
}

export function getMaintenanceStatus(obs = {}) {
  const d = getDecision(obs);
  return String(
    obs.maintenance_status ??
    obs.MAINTENANCE_STATUS ??
    d.maintenance_status ??
    d.MAINTENANCE_STATUS ??
    '—'
  );
}

export function getMaintenanceAction(obs = {}) {
  const d = getDecision(obs);
  return (
    obs.maintenance_action ??
    obs.MAINTENANCE_ACTION ??
    d.maintenance_action ??
    d.MAINTENANCE_ACTION ??
    obs.recommended_operator_action ??
    d.recommended_operator_action ??
    ''
  );
}

function normaliseParameterName(value) {
  if (value === null || value === undefined) return null;
  const text = String(value).trim().toLowerCase();
  if (['temperature', 'temp', 'air temperature'].includes(text)) return 'temperature';
  if (['pressure', 'air pressure', 'barometric pressure', 'press'].includes(text)) return 'pressure';
  if (['humidity', 'relative humidity', 'relative_humidity', 'rh'].includes(text)) return 'humidity';
  if (text.includes('temperature')) return 'temperature';
  if (text.includes('pressure')) return 'pressure';
  if (text.includes('humidity') || text.includes('relative')) return 'humidity';
  return null;
}

export function getRecoveryParameter(obs = {}) {
  const d = getDecision(obs);
  const recovery = obs.recovery || d.recovery || {};
  const candidates = [
    obs.recovery_parameter,
    obs.RECOVERY_PARAMETER,
    recovery.parameter,
    recovery.recovery_parameter,
    d.recovery_parameter,
    d.RECOVERY_PARAMETER,
    d.primary_parameter,
    obs.primary_parameter,
    obs.parameter,
    obs.PARAMETER,
    getRootCause(obs),
    obs.qc_result?.parameter,
    obs.QC_RESULT?.parameter,
  ];

  for (const candidate of candidates) {
    const normalized = normaliseParameterName(candidate);
    if (normalized) return normalized;
  }

  const qc = getQcResult(obs);
  if (qc?.temperature_spike || qc?.temperature_flatline) return 'temperature';
  if (qc?.pressure_spike || qc?.pressure_flatline) return 'pressure';
  if (qc?.humidity_spike || qc?.humidity_flatline) return 'humidity';

  return 'temperature';
}

export function getRecoveryUnit(parameter = 'temperature') {
  const normalized = normaliseParameterName(parameter) || 'temperature';
  if (normalized === 'pressure') return 'hPa';
  if (normalized === 'humidity') return '%';
  return '°C';
}

export function getObservedValueForParameter(obs = {}, parameter = null) {
  const target = normaliseParameterName(parameter || getRecoveryParameter(obs)) || 'temperature';
  if (target === 'pressure') {
    return obs.pressure ?? obs.PRESSURE ?? getPressure(obs) ?? null;
  }
  if (target === 'humidity') {
    return obs.humidity ?? obs.HUMIDITY ?? obs.relative_humidity ?? obs.RELATIVE_HUMIDITY ?? getHumidity(obs) ?? null;
  }
  return obs.temperature ?? obs.TEMPERATURE ?? getTemperature(obs) ?? null;
}

export function getRecoveryMeta(obs = {}) {
  const d = getDecision(obs);
  const recovery = obs.recovery || d.recovery || {};
  const recoveryResults = obs.recovery_results || d.recovery_results || {};
  const parameter = getRecoveryParameter(obs);
  const unit = getRecoveryUnit(parameter);
  const parameterRecovery = recoveryResults[parameter] || {};
  const estimatedValue =
    (parameter === 'temperature' ? obs.estimated_temperature : parameter === 'pressure' ? obs.estimated_pressure : obs.estimated_humidity) ??
    parameterRecovery.estimated_value ??
    parameterRecovery.estimatedValue ??
    (Object.keys(recoveryResults).length <= 1 ? obs.estimated_value : null) ??
    obs.ESTIMATED_VALUE ??
    recovery.estimated_value ??
    recovery.estimatedValue ??
    d.estimated_value ??
    d.estimatedValue ??
    (parameter === 'temperature' ? (obs.estimated_temperature ?? obs.ESTIMATED_TEMPERATURE ?? d.estimated_temperature ?? d.ESTIMATED_TEMPERATURE ?? null) : null) ??
    null;
  const value = Number(estimatedValue);
  return {
    parameter,
    unit,
    label: parameter === 'pressure' ? 'Estimated Pressure' : parameter === 'humidity' ? 'Estimated Relative Humidity' : 'Estimated Temperature',
    observedValue: Number.isFinite(Number(getObservedValueForParameter(obs, parameter))) ? Number(getObservedValueForParameter(obs, parameter)) : null,
    estimatedValue: Number.isFinite(value) ? value : null,
    method: recovery.method || recovery.recovery_method || obs.recovery_method || obs.RECOVERY_METHOD || d.recovery_method || d.RECOVERY_METHOD || null,
    available: String(getRecoveryStatus(obs)).toUpperCase() === 'AVAILABLE',
    previousTimestamp: recovery.previous_timestamp || recovery.previousTimestamp || obs.previous_observation_timestamp || obs.PREVIOUS_OBSERVATION_TIMESTAMP || d.previous_observation_timestamp || d.previousTimestamp || null,
    nextTimestamp: recovery.next_timestamp || recovery.nextTimestamp || obs.next_observation_timestamp || obs.NEXT_OBSERVATION_TIMESTAMP || d.next_observation_timestamp || d.nextTimestamp || null,
  };
}

export function getEstimatedTemperature(obs = {}) {
  const recovery = getRecoveryMeta(obs);
  return recovery.parameter === 'temperature' ? recovery.estimatedValue : null;
}

export function getRecoveryMethod(obs = {}) {
  const d = getDecision(obs);
  const recovery = obs.recovery || d.recovery || {};
  return (
    recovery.method ||
    recovery.recovery_method ||
    obs.recovery_method ||
    obs.RECOVERY_METHOD ||
    d.recovery_method ||
    d.RECOVERY_METHOD ||
    null
  );
}

export function getRecoveryStatus(obs = {}) {
  const d = getDecision(obs);
  const recovery = obs.recovery || d.recovery || {};
  const status =
    obs.recovery_status ??
    obs.RECOVERY_STATUS ??
    recovery.recovery_status ??
    recovery.status ??
    d.recovery_status ??
    d.RECOVERY_STATUS ??
    null;

  if (status !== null && status !== undefined && String(status).trim() !== '') {
    return String(status).toUpperCase();
  }

  const estimatedValue =
    obs.estimated_value ??
    obs.ESTIMATED_VALUE ??
    recovery.estimated_value ??
    recovery.estimatedValue ??
    d.estimated_value ??
    d.estimatedValue ??
    obs.estimated_temperature ??
    obs.ESTIMATED_TEMPERATURE ??
    d.estimated_temperature ??
    d.ESTIMATED_TEMPERATURE;
  const method =
    recovery.method ||
    recovery.recovery_method ||
    obs.recovery_method ||
    obs.RECOVERY_METHOD ||
    d.recovery_method ||
    d.RECOVERY_METHOD;

  return estimatedValue !== null && estimatedValue !== undefined && method ? 'AVAILABLE' : 'UNAVAILABLE';
}

export function getPreviousObservationTimestamp(obs = {}) {
  const d = getDecision(obs);
  return (
    obs.previous_observation_timestamp ||
    obs.PREVIOUS_OBSERVATION_TIMESTAMP ||
    d.previous_observation_timestamp ||
    null
  );
}

export function getNextObservationTimestamp(obs = {}) {
  const d = getDecision(obs);
  return (
    obs.next_observation_timestamp ||
    obs.NEXT_OBSERVATION_TIMESTAMP ||
    d.next_observation_timestamp ||
    null
  );
}

export function getParameter(obs = {}) {
  const d = getDecision(obs);
  return d.primary_parameter || obs.primary_parameter || obs.parameter || 'Observation';
}

export function getHumidity(obs = {}) {
  const d = getDecision(obs);
  return (
    obs.humidity ??
    obs.relative_humidity ??
    obs['Relative Humidity'] ??
    obs.HUMIDITY ??
    d.humidity ??
    d.relative_humidity ??
    null
  );
}

export function getSensorHealthScore(health) {
  const raw =
    health?.overall_snapshot?.overall_health_index ??
    health?.overall_snapshot?.health_score ??
    health?.overall_health_index ??
    health?.overall_health_score ??
    health?.health_score ??
    health?.SENSOR_HEALTH_SCORE ??
    null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

export function getQcResult(obs = {}) {
  return obs.qc_result || obs.QC_RESULT || getDecision(obs).qc_result || {};
}

export function getIforestScore(obs = {}) {
  return obs.iforest_score ?? obs.IFOREST_SCORE ?? getDecision(obs).iforest_score ?? null;
}

export function getLstmMse(obs = {}) {
  return obs.lstm_mse ?? obs.LSTM_MSE ?? getDecision(obs).lstm_mse ?? null;
}

export function getEvidenceScores(obs = {}) {
  return obs.evidence_scores || obs.EVIDENCE_SCORES || getDecision(obs).evidence_scores || {};
}

export function getSpatialResult(obs = {}) {
  return obs.spatial_result || obs.SPATIAL_RESULT || getDecision(obs).spatial_result || {};
}

export function getContributingEvidence(obs = {}) {
  return obs.contributing_evidence || obs.CONTRIBUTING_EVIDENCE || getDecision(obs).contributing_evidence || [];
}


export function getTemperature(obs = {}) {
  return obs.temperature ?? obs.TEMPERATURE ?? null;
}

export function getPressure(obs = {}) {
  return obs.pressure ?? obs.PRESSURE ?? null;
}

export function isAnomaly(obs = {}) {
  return getClassification(obs) !== 'NORMAL';
}

export function formatClassification(value) {
  const text = String(value || 'NORMAL').toUpperCase();
  if (text === 'LIKELY_SENSOR_DATA_FAULT') return 'Likely Sensor/Data Fault';
  if (text === 'LIKELY_GENUINE_WEATHER_EVENT') return 'Likely Genuine Weather Event';
  if (text === 'UNCERTAIN') return 'Uncertain';
  return 'Normal';
}

export function getStationName(obs = {}, stations = []) {
  const stId = obs.station_id || obs.STATION_ID || obs.station;
  if (!stId) return 'Maitri AWS';
  const match = stations.find((s) => s.station_id === stId || s.id === stId);
  if (match?.station_name) return match.station_name;
  if (match?.name) return match.name;
  if (stId.includes('MAITRI')) return 'Maitri AWS';
  if (stId.includes('NOVO')) return 'Novo AWS';
  return stId;
}

export function getAffectedParameter(obs = {}) {
  const d = getDecision(obs);
  const backendParameters = obs.affected_parameters || d.affected_parameters;
  if (Array.isArray(backendParameters) && backendParameters.length > 0) {
    const labels = backendParameters.map((parameter) => {
      const normalized = normaliseParameterName(parameter);
      if (normalized === 'temperature') return 'Temperature';
      if (normalized === 'pressure') return 'Pressure';
      if (normalized === 'humidity') return 'Relative Humidity';
      return String(parameter);
    });
    return labels.join(', ');
  }

  const primary = d.primary_parameter || obs.primary_parameter || obs.parameter;

  const qc = getQcResult(obs);
  const spikeCount = [qc.temperature_spike, qc.pressure_spike, qc.humidity_spike].filter(Boolean).length;
  const flatlineCount = [qc.temperature_flatline, qc.pressure_flatline, qc.humidity_flatline].filter(Boolean).length;

  if (spikeCount + flatlineCount > 1) return 'Multiple';

  if (primary) {
    const pLower = String(primary).toLowerCase();
    if (pLower === 'temperature') return 'Temperature';
    if (pLower === 'pressure') return 'Pressure';
    if (pLower === 'humidity' || pLower === 'relative humidity' || pLower === 'relative_humidity') return 'Relative Humidity';
    if (pLower === 'multivariate' || pLower === 'all') return 'Multiple';
    if (pLower === 'data_quality' || pLower === 'data quality') return 'Data Quality';
  }

  if (qc.temperature_spike || qc.temperature_flatline) return 'Temperature';
  if (qc.pressure_spike || qc.pressure_flatline) return 'Pressure';
  if (qc.humidity_spike || qc.humidity_flatline) return 'Relative Humidity';
  if (qc.missing_flag || qc.gap_flag) return 'Data Quality';

  return 'Multiple';
}

export function getCalibratedDecisionConfidence(obs = {}) {
  const d = getDecision(obs);
  const raw = obs.calibrated_confidence ?? obs.CALIBRATED_CONFIDENCE ?? d.calibrated_confidence;
  if (raw === undefined || raw === null || raw === '') return null;
  const val = Number(raw);
  if (!Number.isFinite(val)) return null;
  return val <= 1 ? Math.round(val * 100) : Math.round(val);
}

export function analyzeEvidence(obs = {}) {
  const detectors = obs.detectors || {};
  const qc = detectors.qc || {};
  const iforest = detectors.isolation_forest || {};
  const lstm = detectors.lstm || {};
  const physical = detectors.physical_consistency || {};
  const multivariate = detectors.multivariate_consistency || {};
  const spatial = detectors.spatial_validation || {};
  const d = getDecision(obs);
  const evScores = getEvidenceScores(obs);

  const qcStatus = (qc.status === 'FLAGGED' || (qc.qc_flag && qc.qc_flag !== 'PASSED')) ? 'FLAGGED' : 'CLEAR';
  const ifStatus = (iforest.status === 'FLAGGED' || Boolean(obs.iforest_flag) || Boolean(obs.if_anomaly)) ? 'FLAGGED' : (iforest.status || 'CLEAR');
  const lstmStatus = (!lstm.available && (lstm.status === 'UNAVAILABLE' || lstm.available === false))
    ? 'UNAVAILABLE'
    : ((lstm.status === 'FLAGGED' || Boolean(obs.lstm_flag) || Boolean(obs.lstm_anomaly)) ? 'FLAGGED' : 'CLEAR');

  const physFlag = physical.status === 'FLAGGED' || physical.flagged;
  const multiFlag = multivariate.status === 'FLAGGED' || multivariate.flagged || Boolean(multivariate.is_anomaly) || Boolean(obs.multivariate_anomaly);
  const physMultiStatus = (physFlag || multiFlag) ? 'FLAGGED' : 'CLEAR';

  const rawSpatialStatus = spatial.status || obs.spatial_result?.spatial_status;
  const spatialStatus = (rawSpatialStatus === 'FLAGGED')
    ? 'FLAGGED'
    : ((rawSpatialStatus === 'UNAVAILABLE' || !rawSpatialStatus || rawSpatialStatus === 'NOT_APPLICABLE') ? 'UNAVAILABLE' : 'CLEAR');

  const availableDetectors = [
    {
      name: 'Rule-Based Quality Control',
      key: 'qc',
      status: qcStatus,
      flagged: qcStatus === 'FLAGGED',
      available: true
    },
    {
      name: 'Isolation Forest (ML)',
      key: 'iforest',
      status: ifStatus,
      flagged: ifStatus === 'FLAGGED',
      available: ifStatus !== 'UNAVAILABLE'
    },
    {
      name: 'LSTM Autoencoder (DL)',
      key: 'lstm',
      status: lstmStatus,
      flagged: lstmStatus === 'FLAGGED',
      available: lstmStatus !== 'UNAVAILABLE'
    },
    {
      name: 'Physical / Multivariate Consistency',
      key: 'physical_multivariate',
      status: physMultiStatus,
      flagged: physMultiStatus === 'FLAGGED',
      available: true
    },
    {
      name: 'Spatial Validation',
      key: 'spatial',
      status: spatialStatus,
      flagged: spatialStatus === 'FLAGGED',
      available: spatialStatus !== 'UNAVAILABLE'
    }
  ];

  const totalAvailable = 4;
  const coreDetectors = availableDetectors.filter(p => p.key !== 'spatial');
  const flaggedCount = coreDetectors.filter(p => p.flagged).length;
  const agreementPercentage = Math.round((flaggedCount / totalAvailable) * 100);

  const rawPhysScore =
    physical.score ??
    obs.physical_score ??
    obs.PHYSICAL_SCORE ??
    d.physical_score ??
    d.physical_result?.score ??
    d.physical_result?.thermodynamic_violation ??
    evScores.physical_consistency ??
    null;

  const rawMultiScore =
    multivariate.score ??
    obs.multivariate_score ??
    obs.MULTIVARIATE_SCORE ??
    d.multivariate_score ??
    evScores.multivariate_consistency ??
    null;

  let combinedScore = rawMultiScore ?? rawPhysScore;
  if (combinedScore === null || combinedScore === undefined || (combinedScore === 0 && physMultiStatus === 'FLAGGED')) {
    if (physMultiStatus === 'FLAGGED') {
      combinedScore = 1.0;
    } else {
      combinedScore = 0.0;
    }
  }

  return {
    flaggedCount,
    totalAvailable,
    agreementPercentage,
    availableDetectors,
    detectors: {
      qc: {
        available: true,
        flagged: qcStatus === 'FLAGGED',
        status: qcStatus,
        reasons: qc.qc_reasons || [],
        flagStr: qc.qc_flag || 'PASSED',
        tempSpike: Boolean(qc.temperature_spike),
        pressSpike: Boolean(qc.pressure_spike),
        humSpike: Boolean(qc.humidity_spike),
      },
      iforest: {
        available: ifStatus !== 'UNAVAILABLE',
        flagged: ifStatus === 'FLAGGED',
        status: ifStatus,
        rawScore: iforest.score ?? obs.iforest_score ?? null,
        evidenceScore: null,
      },
      lstm: {
        available: lstmStatus !== 'UNAVAILABLE',
        flagged: lstmStatus === 'FLAGGED',
        status: lstmStatus,
        mse: lstm.reconstruction_error ?? obs.lstm_mse ?? null,
        threshold: null,
        evidenceScore: null,
      },
      physical: {
        available: physical.status !== 'UNAVAILABLE',
        flagged: physical.status === 'FLAGGED',
        status: physical.status || 'CLEAR',
        score: rawPhysScore ?? combinedScore,
        dewPoint: physical.dew_point ?? null,
      },
      multivariate: {
        available: multivariate.status !== 'UNAVAILABLE',
        flagged: multivariate.status === 'FLAGGED',
        status: multivariate.status || 'CLEAR',
        score: rawMultiScore ?? combinedScore,
        isAnomaly: Boolean(multivariate.is_anomaly),
      },
      physicalMultivariate: {
        available: true,
        flagged: physMultiStatus === 'FLAGGED',
        status: physMultiStatus,
        score: combinedScore,
      },
      spatial: {
        available: spatialStatus !== 'UNAVAILABLE',
        flagged: spatialStatus === 'FLAGGED',
        status: spatialStatus,
        score: spatial.evidence_score ?? null,
        buddyStation: spatial.buddy_station || null,
      },
    },
  };
}

export function getAlertUniqueId(obs = {}) {
  if (!obs) return '';
  if (obs.alert_key) return String(obs.alert_key);
  if (obs.db_id) return `db_${obs.db_id}`;
  if (obs.alert_id) return `alert_${obs.alert_id}`;

  const ts = obs.timestamp || obs.TIMESTAMP || '';
  const st = obs.station_id || obs.STATION_ID || 'AWS-MAITRI-89514';
  const param = getAffectedParameter(obs) || obs.parameter || '';
  const cause = getRootCause(obs) || obs.classification || '';

  let normTs = String(ts).trim();
  try {
    const d = new Date(ts);
    if (!isNaN(d.getTime())) {
      normTs = d.toISOString();
    }
  } catch (e) {}

  return `${st}|${normTs}|${param}|${cause}`.toLowerCase();
}


