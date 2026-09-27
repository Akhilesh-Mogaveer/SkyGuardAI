"""Data Quality Report Generator for SkyGuard AI.

Generates comprehensive meteorological data quality audit reports in both
structured JSON and publication-ready Markdown formats.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

import pandas as pd

from backend.app.config import settings

logger = logging.getLogger("skyguard.quality_report")


class DataQualityReport:
    """Encapsulates AWS observation data quality metrics and report formatting."""

    def __init__(self, audit_summary: Dict[str, Any], station_metadata: Optional[Dict[str, Any]] = None) -> None:
        self.summary = audit_summary
        merged_meta = {
            "station_id": settings.DEFAULT_STATION_ID,
            "station_name": settings.DEFAULT_STATION_NAME,
            "latitude": settings.STATION_LATITUDE,
            "longitude": settings.STATION_LONGITUDE,
            "elevation_m": settings.STATION_ELEVATION_M,
        }
        if station_metadata:
            merged_meta.update(station_metadata)
        self.station_metadata = merged_meta

    def to_dict(self) -> Dict[str, Any]:
        """Returns JSON-serializable dictionary representation of the report."""
        gaps_df = self.summary.get("gaps_detail")
        top_gaps = []
        if isinstance(gaps_df, pd.DataFrame) and not gaps_df.empty:
            # Extract top 10 longest gaps
            top_10 = gaps_df.sort_values(by="duration_hours", ascending=False).head(10)
            for _, r in top_10.iterrows():
                top_gaps.append({
                    "gap_id": int(r["gap_id"]),
                    "gap_start": str(r["gap_start"]),
                    "gap_end": str(r["gap_end"]),
                    "duration_hours": float(r["duration_hours"]),
                    "duration_days": float(r["duration_days"]),
                    "missing_steps": int(r["missing_steps"]),
                })

        return {
            "station_metadata": self.station_metadata,
            "overview": {
                "raw_rows": self.summary.get("raw_rows", 0),
                "cleaned_rows": self.summary.get("cleaned_rows", 0),
                "date_range": {
                    "start": self.summary.get("date_start"),
                    "end": self.summary.get("date_end"),
                },
                "duplicate_timestamps": self.summary.get("duplicate_timestamps", 0),
                "continuous_segments_count": self.summary.get("continuous_segments_count", 0),
            },
            "missing_values": self.summary.get("missing_values", {}),
            "time_gaps": {
                "total_gaps": self.summary.get("total_gaps", 0),
                "statistics": self.summary.get("gap_statistics", {}),
                "top_longest_gaps": top_gaps,
            },
            "parameter_statistics": self.summary.get("parameter_statistics", {}),
        }

    def to_markdown(self) -> str:
        """Generates a detailed, human-readable GitHub Flavored Markdown report."""
        report = self.to_dict()
        meta = report["station_metadata"]
        ov = report["overview"]
        gaps = report["time_gaps"]
        gap_stats = gaps["statistics"]
        missing = report["missing_values"]
        params = report["parameter_statistics"]

        lines = [
            f"# 🛡️ SkyGuard AI — Data Quality & Integrity Report",
            f"",
            f"**Station:** {meta['station_name']} (`{meta['station_id']}`)",
            f"**Location:** Lat: {meta['latitude']}°, Lon: {meta['longitude']}°, Elevation: {meta['elevation_m']}m MSL",
            f"",
            f"---",
            f"",
            f"## 1. Dataset Overview & Chronology",
            f"",
            f"| Metric | Value |",
            f"|:---|:---|",
            f"| **Total Raw Records** | {ov['raw_rows']:,} |",
            f"| **Cleaned Working Records** | {ov['cleaned_rows']:,} |",
            f"| **Observation Start Time** | `{ov['date_range']['start']}` |",
            f"| **Observation End Time** | `{ov['date_range']['end']}` |",
            f"| **Duplicate Timestamps** | {ov['duplicate_timestamps']} |",
            f"| **Continuous Hourly Segments** | {ov['continuous_segments_count']} |",
            f"",
            f"---",
            f"",
            f"## 2. Missing Value Analysis",
            f"",
            f"| Meteorological Parameter | Valid Count | Missing (NaN) Count | Missing % | Max Consecutive Missing |",
            f"|:---|---:|---:|---:|---:|",
        ]

        for col, m in missing.items():
            lines.append(
                f"| **{col}** | {m['valid_count']:,} | {m['missing_count']:,} | {m['missing_pct']}% | {m['max_consecutive_missing']:,} |"
            )

        lines.extend([
            f"",
            f"> [!NOTE]",
            f"> Sentinel missing values (`-999`, `-9999`) have been cleanly translated to IEEE 754 `NaN`. "
            f"`relative_humidity` is densely populated from 2015-01-01 onwards.",
            f"",
            f"---",
            f"",
            f"## 3. Time Gap Detection & Duration Profiling",
            f"",
            f"**Total Discontinuous Gap Transitions (> 1.0 hr):** {gaps['total_gaps']:,}",
            f"",
            f"| Gap Metric | Duration (Hours) | Duration (Days) |",
            f"|:---|---:|---:|",
            f"| **Minimum Gap** | {gap_stats.get('min_gap_hours', 0.0):.1f} hrs | {gap_stats.get('min_gap_hours', 0.0)/24.0:.2f} days |",
            f"| **Median Gap** | {gap_stats.get('median_gap_hours', 0.0):.1f} hrs | {gap_stats.get('median_gap_hours', 0.0)/24.0:.2f} days |",
            f"| **Mean Gap** | {gap_stats.get('mean_gap_hours', 0.0):.1f} hrs | {gap_stats.get('mean_gap_hours', 0.0)/24.0:.2f} days |",
            f"| **90th Percentile Gap** | {gap_stats.get('p90_gap_hours', 0.0):.1f} hrs | {gap_stats.get('p90_gap_hours', 0.0)/24.0:.2f} days |",
            f"| **Maximum Gap** | {gap_stats.get('max_gap_hours', 0.0):.1f} hrs | {gap_stats.get('max_gap_hours', 0.0)/24.0:.2f} days |",
            f"| **Cumulative Missing Span** | {gap_stats.get('total_missing_hours', 0.0):,.1f} hrs | {gap_stats.get('total_missing_hours', 0.0)/24.0:,.1f} days |",
            f"",
            f"### Top Longest Gap Incidents",
            f"",
            f"| Gap # | Gap Start (UTC) | Gap End (UTC) | Duration (Hours) | Duration (Days) | Missing Hours |",
            f"|---:|:---|:---|---:|---:|---:|",
        ])

        for g in gaps["top_longest_gaps"]:
            lines.append(
                f"| {g['gap_id']} | `{g['gap_start']}` | `{g['gap_end']}` | {g['duration_hours']:.1f} | {g['duration_days']:.1f} | {g['missing_steps']} |"
            )

        lines.extend([
            f"",
            f"> [!IMPORTANT]",
            f"> **Strict Non-Interpolation Rule Active:** Under meteorological quality standards, no synthetic interpolation is performed across large temporal gaps (> {settings.MAX_ALLOWABLE_INTERPOLATION_HOURS} hours). Downstream LSTM sequence windows are drawn strictly from continuous hourly segments.",
            f"",
            f"---",
            f"",
            f"## 4. Parameter Statistical Distributions",
            f"",
            f"| Parameter | Count | Min | Q25 (25%) | Median (50%) | Mean | Q75 (75%) | Max | Std Dev |",
            f"|:---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])

        for col, p in params.items():
            lines.append(
                f"| **{col}** | {p['count']:,} | {p['min']} | {p['q25']} | {p['median']} | {p['mean']} | {p['q75']} | {p['max']} | {p['std']} |"
            )

        lines.extend([
            f"",
            f"---",
            f"*Report automatically generated by SkyGuard AI Quality Engine.*",
        ])

        return "\n".join(lines)

    def save(self, output_dir: Optional[Union[str, Path]] = None) -> Tuple[Path, Path]:
        """Saves report artifacts to disk in both JSON and Markdown formats.
        
        Args:
            output_dir: Destination directory. Defaults to data/processed.
            
        Returns:
            Tuple[Path, Path]: Paths to saved (json_path, markdown_path).
        """
        out_dir = Path(output_dir or settings.PROCESSED_DATA_DIR).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        json_path = out_dir / "data_quality_report.json"
        md_path = out_dir / "data_quality_report.md"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self.to_markdown())

        logger.info("Saved Data Quality Reports to:\n - %s\n - %s", json_path, md_path)
        return json_path, md_path
