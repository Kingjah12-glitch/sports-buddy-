"""V4 runtime model: standardised logistic regression stored as plain JSON
(no scikit-learn needed at runtime). Trained by backtest_v4.py."""
import json
import math
from pathlib import Path


class LogisticModel:
    def __init__(self, spec: dict):
        self.features = spec["features"]
        self.markets = spec["markets"]
        self.trained_through = spec.get("trained_through")

    def predict(self, market: str, feats: dict) -> float:
        m = self.markets[market]
        z = m["intercept"]
        for name, mean, scale, coef in zip(self.features, m["mean"], m["scale"], m["coef"]):
            z += coef * (feats[name] - mean) / scale
        p = 1.0 / (1.0 + math.exp(-z))
        return min(0.99, max(0.01, p))


def load_model(path: Path):
    try:
        return LogisticModel(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return None


class OutcomeModel:
    """Standardised multinomial logistic regression: home / draw / away."""

    def __init__(self, spec: dict):
        self.features = spec["features"]
        self.mean, self.scale = spec["mean"], spec["scale"]
        self.coef, self.intercept = spec["coef"], spec["intercept"]

    def predict(self, feats: dict):
        z = []
        for coefs, b in zip(self.coef, self.intercept):
            v = b
            for name, mean, scale, c in zip(self.features, self.mean, self.scale, coefs):
                v += c * (feats[name] - mean) / scale
            z.append(v)
        top = max(z)
        e = [math.exp(v - top) for v in z]
        total = sum(e)
        return tuple(v / total for v in e)


def load_outcome_model(path: Path):
    try:
        return OutcomeModel(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return None
