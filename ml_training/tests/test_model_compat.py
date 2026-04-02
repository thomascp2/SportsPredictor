"""
Smoke tests for all 19 models in the local model registry.

All tests are marked @pytest.mark.integration — they require the local
model_registry directory to be present. Tests are skipped when the
registry directory does not exist (CI / fresh checkout).
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pytest

from ml_training.model_manager import ModelMetadata

REGISTRY_DIR = Path(__file__).parent.parent / 'model_registry'


def _get_all_model_dirs():
    """
    Walk REGISTRY_DIR/{nba,nhl}/*/ looking for directories containing model.joblib.
    Returns list of Path objects.
    """
    model_dirs = []
    for sport in ('nba', 'nhl'):
        sport_dir = REGISTRY_DIR / sport
        if not sport_dir.exists():
            continue
        for prop_dir in sport_dir.iterdir():
            if not prop_dir.is_dir():
                continue
            # Find version subdirectories
            for version_dir in prop_dir.iterdir():
                if version_dir.is_dir() and (version_dir / 'model.joblib').exists():
                    model_dirs.append(version_dir)
    return model_dirs


def _get_latest_model_dirs():
    """Return only the latest version dir for each prop, based on latest.txt or sorted."""
    latest_dirs = []
    for sport in ('nba', 'nhl'):
        sport_dir = REGISTRY_DIR / sport
        if not sport_dir.exists():
            continue
        for prop_dir in sport_dir.iterdir():
            if not prop_dir.is_dir():
                continue
            # Check latest.txt
            latest_file = prop_dir / 'latest.txt'
            if latest_file.exists():
                version = latest_file.read_text().strip()
                version_dir = prop_dir / version
                if version_dir.exists() and (version_dir / 'model.joblib').exists():
                    latest_dirs.append(version_dir)
                    continue
            # Fallback: sorted
            versions = sorted(
                [d for d in prop_dir.iterdir() if d.is_dir() and (d / 'model.joblib').exists()],
                key=lambda d: d.name,
            )
            if versions:
                latest_dirs.append(versions[-1])
    return latest_dirs


@pytest.mark.integration
def test_all_models_load():
    """Load model.joblib and scaler.joblib for each model in the registry."""
    if not REGISTRY_DIR.exists():
        pytest.skip(f"Registry directory not found: {REGISTRY_DIR}")

    model_dirs = _get_latest_model_dirs()
    assert len(model_dirs) >= 19, (
        f"Expected at least 19 models in registry, found {len(model_dirs)}"
    )

    for model_dir in model_dirs:
        model = joblib.load(model_dir / 'model.joblib')
        scaler = joblib.load(model_dir / 'scaler.joblib')
        assert model is not None, f"Model failed to load from {model_dir}"
        assert scaler is not None, f"Scaler failed to load from {model_dir}"


@pytest.mark.integration
def test_all_metadata_loads():
    """Load metadata.json and construct ModelMetadata for each model — no TypeError."""
    if not REGISTRY_DIR.exists():
        pytest.skip(f"Registry directory not found: {REGISTRY_DIR}")

    model_dirs = _get_latest_model_dirs()
    assert len(model_dirs) >= 19, (
        f"Expected at least 19 models in registry, found {len(model_dirs)}"
    )

    loaded = 0
    for model_dir in model_dirs:
        metadata_path = model_dir / 'metadata.json'
        assert metadata_path.exists(), f"metadata.json missing in {model_dir}"
        with open(metadata_path, 'r') as f:
            data = json.load(f)
        # Should not raise TypeError even with old metadata lacking Phase 2 fields
        meta = ModelMetadata(**data)
        assert meta.sport is not None
        loaded += 1

    assert loaded >= 19, f"Expected at least 19 metadata objects loaded, got {loaded}"


@pytest.mark.integration
def test_predict_proba_all_models():
    """For each model, call predict_proba on dummy input and assert shape is (1, 2)."""
    if not REGISTRY_DIR.exists():
        pytest.skip(f"Registry directory not found: {REGISTRY_DIR}")

    model_dirs = _get_latest_model_dirs()
    assert len(model_dirs) >= 19

    for model_dir in model_dirs:
        model = joblib.load(model_dir / 'model.joblib')
        scaler = joblib.load(model_dir / 'scaler.joblib')

        metadata_path = model_dir / 'metadata.json'
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)

        n_features = len(metadata['feature_names'])
        dummy = np.zeros((1, n_features))
        dummy_scaled = scaler.transform(dummy)
        proba = model.predict_proba(dummy_scaled)

        assert proba.shape == (1, 2), (
            f"Expected predict_proba shape (1, 2) for {model_dir.name}, got {proba.shape}"
        )
