"""Load the trained late-delivery risk model and score one supplier."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import joblib
import pandas as pd

from ml.features import RECENT_WINDOW, features_for_order

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_FILE = "reliability_model.joblib"
METADATA_FILE = "reliability_model.json"


@dataclass
class ReliabilityPrediction:
    late_probability: float
    on_time_probability: float
    risk_level: str
    model_version: str
    model_name: str
    trained_on: str
    history_count: int
    signals: list[dict]
    method: str = "ml_model"

    def as_dict(self) -> dict:
        return asdict(self)


def _percent(rate: float) -> int:
    return math.floor(rate * 100 + 1e-9)


def _signals(row: pd.Series) -> list[dict]:
    """Plain-language reasons derived only from the feature values."""
    count = int(row["prior_count"])
    if count == 0:
        return [{"text": "No delivery history with this supplier yet", "direction": "raises_risk"}]

    signals = []
    recent_late = float(row["recent_late_rate"])
    recent_total = min(count, RECENT_WINDOW)
    if recent_late >= 0.3:
        signals.append({"text": f"Late on {round(recent_late * recent_total)} of the last "
                                f"{recent_total} deliveries", "direction": "raises_risk"})
    elif recent_late == 0 and recent_total >= 3:
        signals.append({"text": f"On time for all of the last {recent_total} deliveries",
                        "direction": "lowers_risk"})

    on_time = float(row["prior_on_time_rate"])
    if on_time >= 0.9 and count >= 5:
        signals.append({"text": f"On time for {_percent(on_time)}% of {count} past deliveries",
                        "direction": "lowers_risk"})
    elif on_time < 0.7:
        signals.append({"text": f"On time for only {_percent(on_time)}% of {count} past "
                                f"deliveries", "direction": "raises_risk"})

    mean_delay = float(row["prior_mean_delay_days"])
    if mean_delay >= 7 and on_time < 1:
        # prior_mean_delay_days averages over all past orders; divide by the late share
        # to get the average delay of the late ones.
        late_delay = mean_delay / (1 - on_time)
        signals.append({"text": f"Late deliveries averaged {late_delay:.0f} days",
                        "direction": "raises_risk"})

    if row["shipment_mode"] == "Ocean":
        signals.append({"text": "Ocean freight", "direction": "neutral"})
    return signals


class ReliabilityModel:
    def __init__(self, pipeline, metadata: dict):
        self.pipeline = pipeline
        self.metadata = metadata

    @classmethod
    def load(cls, artifact_dir: Path | None = None) -> "ReliabilityModel | None":
        directory = Path(artifact_dir) if artifact_dir is not None else ARTIFACT_DIR
        model_path, metadata_path = directory / MODEL_FILE, directory / METADATA_FILE
        if not (model_path.is_file() and metadata_path.is_file()):
            return None
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return cls(joblib.load(model_path), metadata)

    def predict_for_supplier(self, history: pd.DataFrame, order: dict,
                             as_of: pd.Timestamp | None = None) -> ReliabilityPrediction:
        features = features_for_order(history, order, as_of)
        late = float(self.pipeline.predict_proba(
            features[self.metadata["feature_columns"]])[:, 1][0])
        bands = self.metadata["risk_bands"]
        if late >= bands["high"]:
            risk_level = "high"
        elif late >= bands["medium"]:
            risk_level = "medium"
        else:
            risk_level = "low"
        row = features.iloc[0]
        return ReliabilityPrediction(
            late_probability=late,
            on_time_probability=1.0 - late,
            risk_level=risk_level,
            model_version=self.metadata["model_version"],
            model_name=self.metadata["model_name"],
            trained_on=self.metadata["trained_on"],
            history_count=int(row["prior_count"]),
            signals=_signals(row),
        )
