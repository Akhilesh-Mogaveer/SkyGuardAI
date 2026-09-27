CREATE TABLE IF NOT EXISTS stations (
    id SERIAL PRIMARY KEY,
    station_id VARCHAR(100) UNIQUE NOT NULL,
    station_name VARCHAR(200),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    country VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS observations (
    id SERIAL PRIMARY KEY,
    station_id VARCHAR(100),
    timestamp TIMESTAMP NOT NULL,
    temperature DOUBLE PRECISION,
    pressure DOUBLE PRECISION,
    humidity DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    station_id VARCHAR(100),
    timestamp TIMESTAMP NOT NULL,
    severity VARCHAR(50),
    assessment VARCHAR(100),
    parameter VARCHAR(100),
    observed_value DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    root_cause TEXT
);