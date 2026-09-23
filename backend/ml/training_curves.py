"""How much training each candidate model gets, and where it stops improving.

Tree models have no epochs. The closest measurable things are the number of trees (Random
Forest), the number of boosting rounds (gradient boosting) and solver iterations (logistic
regression). Every curve is 5-fold cross-validated PR-AUC on the training period only
(2006-2013), so the held-out 2014-2015 test set is never touched.

Usage (from backend/):  python -m ml.training_curves
"""
from __future__ import annotations

import json

import numpy as np
from sklearn.base import clone
from sklearn.metrics import average_precision_score
from sklearn.model_selection import StratifiedKFold

from ml.features import FEATURE_COLUMNS, build_training_frame
from ml.scms import load_scms, scms_orders
from ml.train_reliability import DEFAULT_OUTPUT_DIR, _candidates

TREES = [10, 25, 50, 100, 150, 200, 300, 500]
DEPTHS = [2, 4, 6, 8, 10, 12, None]


def _cv(pipeline, x, y, folds, **params) -> float:
    scores = []
    for fit, val in folds.split(x, y):
        model = clone(pipeline).set_params(**params).fit(x.iloc[fit], y[fit])
        scores.append(average_precision_score(y[val], model.predict_proba(x.iloc[val])[:, 1]))
    return round(float(np.mean(scores)), 4)


def curves() -> dict:
    frame = build_training_frame(scms_orders(load_scms()))
    train = frame[frame["scheduled_date"].dt.year <= 2013]
    x, y = train[FEATURE_COLUMNS], train["late"].to_numpy(dtype=int)
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    models = _candidates(42)

    rf = models["random_forest"]
    trees = {n: _cv(rf, x, y, folds, classifier__n_estimators=n) for n in TREES}
    depths = {str(d): _cv(rf, x, y, folds, classifier__max_depth=d) for d in DEPTHS}

    # Boosting rounds: score every round of each fold's model, like a per-epoch validation curve.
    # Allowed 1,000 rounds (the shipped config has 300) to see where the curve actually peaks.
    hgb = clone(models["hist_gradient_boosting"]).set_params(classifier__max_iter=1000)
    per_round = []
    for fit, val in folds.split(x, y):
        model = clone(hgb).fit(x.iloc[fit], y[fit])
        staged = model[-1].staged_predict_proba(model[:-1].transform(x.iloc[val]))
        per_round.append([average_precision_score(y[val], p[:, 1]) for p in staged])
    rounds = np.mean([r[:min(map(len, per_round))] for r in per_round], axis=0)

    # Shuffled folds mix years; a time-ordered check (fit 2006-2011, score 2012-2013) shows
    # whether deeper trees still win on later shipments. Still inside the training period.
    early = (train["scheduled_date"].dt.year <= 2011).to_numpy()
    def later(depth):
        model = clone(rf).set_params(classifier__max_depth=depth).fit(x[early], y[early])
        return round(float(average_precision_score(y[~early], model.predict_proba(x[~early])[:, 1])), 4)
    depth_later = {str(d): later(d) for d in DEPTHS}

    lr_iterations = int(clone(models["logistic_regression"]).fit(x, y)[-1].n_iter_.max())
    return {
        "random_forest_trees": trees,
        "random_forest_depth": depths,
        "random_forest_depth_later_years": depth_later,
        "boosting_rounds": {"configured": 300, "measured_up_to": len(rounds), "best_round": int(np.argmax(rounds)) + 1,
                            "best_pr_auc": round(float(rounds.max()), 4),
                            "at_round": {n: round(float(rounds[n - 1]), 4) for n in (10, 25, 50, 100, 200, 300, 400, 500, 600, 800, 1000)
                                         if n <= len(rounds)}},
        "logistic_regression_iterations": {"configured_max": 2000, "used": lr_iterations},
    }


if __name__ == "__main__":
    result = curves()
    (DEFAULT_OUTPUT_DIR / "training_curves.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
