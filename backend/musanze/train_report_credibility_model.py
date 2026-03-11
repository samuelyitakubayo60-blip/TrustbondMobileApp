import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_auc_score,
    roc_curve,
    precision_recall_curve,
    average_precision_score,
)
from sklearn.model_selection import RandomizedSearchCV, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "report_credibility_training.csv"
MODEL_PATH = ROOT / "TrustBond.joblib"
METADATA_PATH = ROOT / "TrustBond.json"


def load_data(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    # Use only rows marked as usable for training
    if "used_for_training" in df.columns:
        df = df[df["used_for_training"] == 1].copy()

    # Drop any obviously broken rows
    df = df.dropna(subset=["ground_truth_label"])
    return df


def prepare_features(df: pd.DataFrame):
    # Target: real=1, fake=0
    y = (df["ground_truth_label"].str.lower() == "real").astype(int)

    # Feature columns (exclude target + helper columns)
    drop_cols = {
        "ground_truth_label",
        "decision",
        "confidence_level",
        "used_for_training",
    }
    feature_cols = [c for c in df.columns if c not in drop_cols]

    X = df[feature_cols].copy()

    # Identify types
    numeric_cols = [
        c
        for c in feature_cols
        if pd.api.types.is_numeric_dtype(X[c])
    ]

    categorical_cols = [
        c
        for c in feature_cols
        if c not in numeric_cols
    ]

    return X, y, numeric_cols, categorical_cols


def extract_feature_importances(
    model: Pipeline, numeric_cols, categorical_cols
) -> list[dict]:
    """
    Extract feature importances from the fitted XGBoost model, mapped back to
    human-readable feature names after preprocessing (if supported by sklearn version).
    """
    try:
        preprocessor = model.named_steps["preprocessor"]
        clf: XGBClassifier = model.named_steps["clf"]  # type: ignore[assignment]

        # Get expanded feature names after ColumnTransformer + OneHotEncoder
        feature_names = preprocessor.get_feature_names_out()
        importances = clf.feature_importances_

        pairs = [
            {"feature": str(name), "importance": float(imp)}
            for name, imp in zip(feature_names, importances)
        ]
        # Sort descending and keep top 50 for readability
        pairs.sort(key=lambda x: x["importance"], reverse=True)
        return pairs[:50]
    except Exception:
        # Fallback: return empty list if anything goes wrong
        return []


def build_pipeline(numeric_cols, categorical_cols) -> Pipeline:
    # Preprocessing: pass numeric through, one-hot encode categoricals
    numeric_transformer = "passthrough"
    categorical_transformer = OneHotEncoder(handle_unknown="ignore")

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", numeric_transformer, numeric_cols),
            ("cat", categorical_transformer, categorical_cols),
        ]
    )

    # Base XGBoost model (we'll tune hyperparameters around this)
    xgb = XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",   # fast on CPU
        use_label_encoder=False,
        n_estimators=300,
        learning_rate=0.05,
        max_depth=5,
        subsample=0.8,
        colsample_bytree=0.8,
        n_jobs=-1,
    )

    pipe = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("clf", xgb),
        ]
    )
    return pipe


def tune_hyperparameters(pipe: Pipeline, X_train, y_train):
    # Parameter space for XGBoost classifier inside pipeline
    param_distributions = {
        "clf__n_estimators": [200, 300, 400, 600],
        "clf__max_depth": [3, 4, 5, 6, 8],
        "clf__learning_rate": [0.01, 0.03, 0.05, 0.1],
        "clf__subsample": [0.7, 0.8, 0.9, 1.0],
        "clf__colsample_bytree": [0.7, 0.8, 0.9, 1.0],
        "clf__min_child_weight": [1, 3, 5, 7],
        "clf__gamma": [0.0, 0.1, 0.2],
    }

    # Handle class imbalance via scale_pos_weight
    pos = (y_train == 1).sum()
    neg = (y_train == 0).sum()
    if pos > 0:
        scale_pos_weight = neg / pos
    else:
        scale_pos_weight = 1.0

    pipe.set_params(clf__scale_pos_weight=scale_pos_weight)

    search = RandomizedSearchCV(
        pipe,
        param_distributions=param_distributions,
        n_iter=30,               # increase for more thorough search
        scoring="roc_auc",
        n_jobs=-1,
        cv=3,
        verbose=1,
        random_state=42,
    )

    search.fit(X_train, y_train)
    print("Best ROC-AUC (CV):", search.best_score_)
    print("Best params:", search.best_params_)

    return search.best_estimator_, search.best_params_


def find_best_threshold(model: Pipeline, X_valid, y_valid):
    # Get predicted probabilities for the positive class
    y_scores = model.predict_proba(X_valid)[:, 1]

    fpr, tpr, thresholds = roc_curve(y_valid, y_scores)

    # Optimize Youden's J statistic = TPR - FPR (balanced sensitivity/specificity)
    j_scores = tpr - fpr
    best_idx = np.argmax(j_scores)
    best_threshold = float(thresholds[best_idx])

    print("Best threshold by Youden's J:", best_threshold)
    return best_threshold, y_scores


def main():
    if not DATA_PATH.exists():
        raise SystemExit(f"Data file not found: {DATA_PATH}")

    df = load_data(DATA_PATH)
    print(f"Loaded {len(df)} rows for training.")

    X, y, numeric_cols, categorical_cols = prepare_features(df)

    # Split into train/validation/test
    X_train, X_temp, y_train, y_temp = train_test_split(
        X, y, test_size=0.3, stratify=y, random_state=42
    )
    X_valid, X_test, y_valid, y_test = train_test_split(
        X_temp, y_temp, test_size=0.5, stratify=y_temp, random_state=42
    )

    print(
        f"Train size: {len(X_train)}, "
        f"Valid size: {len(X_valid)}, "
        f"Test size: {len(X_test)}"
    )

    pipe = build_pipeline(numeric_cols, categorical_cols)
    best_model, best_params = tune_hyperparameters(pipe, X_train, y_train)

    # Threshold tuning on validation set
    best_threshold, valid_scores = find_best_threshold(best_model, X_valid, y_valid)

    # Additional validation metrics (ROC-AUC and PR-AUC)
    valid_roc_auc = roc_auc_score(y_valid, valid_scores)
    precision, recall, pr_thresholds = precision_recall_curve(y_valid, valid_scores)
    valid_pr_auc = average_precision_score(y_valid, valid_scores)
    print("\n=== Validation performance ===")
    print("ROC-AUC (valid):", valid_roc_auc)
    print("PR-AUC (valid):", valid_pr_auc)

    # Evaluate on test set
    y_test_scores = best_model.predict_proba(X_test)[:, 1]
    y_test_pred = (y_test_scores >= best_threshold).astype(int)

    print("\n=== Test set performance (using tuned threshold) ===")
    test_roc_auc = roc_auc_score(y_test, y_test_scores)
    print("ROC-AUC (test):", test_roc_auc)
    print("Confusion matrix:")
    print(confusion_matrix(y_test, y_test_pred))
    print("\nClassification report:")
    print(classification_report(y_test, y_test_pred, target_names=["fake", "real"]))

    # Extract feature importances for interpretability
    feature_importances = extract_feature_importances(
        best_model, numeric_cols, categorical_cols
    )

    # Save model + metadata (for FastAPI integration)
    joblib.dump(best_model, MODEL_PATH)
    print(f"\nSaved trained model pipeline to: {MODEL_PATH}")

    meta = {
        "best_params": best_params,
        "best_threshold": best_threshold,
        "feature_columns": list(X.columns),
        "numeric_columns": numeric_cols,
        "categorical_columns": categorical_cols,
        "n_rows": len(df),
        "validation": {
            "roc_auc": float(valid_roc_auc),
            "pr_auc": float(valid_pr_auc),
        },
        "test": {
            "roc_auc": float(test_roc_auc),
        },
        "feature_importances_top50": feature_importances,
    }
    with METADATA_PATH.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"Saved metadata to: {METADATA_PATH}")


if __name__ == "__main__":
    main()