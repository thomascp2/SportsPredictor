"""
Model Registry and Manager
==========================

Handles model persistence, versioning, and metadata tracking.
Supports both NHL (JSON features) and NBA (column features) schemas.
"""

import os
import json
import joblib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field


@dataclass
class ModelMetadata:
    """Metadata for a trained model"""
    sport: str
    prop_type: str
    line: float
    model_type: str  # e.g., 'gradient_boosting', 'xgboost'
    version: str     # e.g., 'v20260116_001'
    trained_at: str
    training_samples: int
    feature_names: List[str]

    # Performance metrics
    test_accuracy: float
    test_roc_auc: float
    test_brier_score: float
    test_log_loss: float

    # Baseline comparison
    baseline_accuracy: float
    improvement_over_baseline: float

    # Calibration info
    is_calibrated: bool
    calibration_method: str  # 'isotonic' or 'sigmoid'

    # Training window (0 = all history)
    training_window_days: int = 90

    # Feature importance (top 10)
    top_features: Dict[str, float] = field(default_factory=dict)


class ModelRegistry:
    """
    Central registry for trained ML models.

    Handles:
    - Saving/loading models with joblib
    - Versioning (date-based + increment)
    - Metadata tracking
    - Model selection (best by metric)

    Directory Structure:
        model_registry/
            nhl/
                points_0_5/
                    v20260116_001/
                        model.joblib
                        scaler.joblib
                        metadata.json
                    latest.txt
                shots_2_5/
                    ...
            nba/
                ...
    """

    def __init__(self, registry_dir: str = None):
        """
        Initialize model registry.

        Args:
            registry_dir: Base directory for model storage.
                         Defaults to ml_training/model_registry/
        """
        if registry_dir is None:
            registry_dir = Path(__file__).parent / "model_registry"

        self.registry_dir = Path(registry_dir)
        self.registry_dir.mkdir(parents=True, exist_ok=True)

    def _get_model_dir(self, sport: str, prop_type: str, line: float) -> Path:
        """Get directory for a specific model"""
        # Convert line to safe directory name (0.5 -> 0_5)
        line_str = str(line).replace('.', '_')
        dir_name = f"{prop_type}_{line_str}"
        model_dir = self.registry_dir / sport.lower() / dir_name
        model_dir.mkdir(parents=True, exist_ok=True)
        return model_dir

    def save_model(
        self,
        model,
        scaler,
        metadata: ModelMetadata,
        sport: str,
        prop_type: str,
        line: float
    ) -> str:
        """
        Save a trained model with its scaler and metadata.

        Args:
            model: Trained sklearn/xgboost model
            scaler: Fitted StandardScaler
            metadata: ModelMetadata object
            sport: 'nhl' or 'nba'
            prop_type: 'points', 'shots', etc.
            line: Betting line (0.5, 2.5, etc.)

        Returns:
            Version string of saved model
        """
        model_dir = self._get_model_dir(sport, prop_type, line)

        # Generate version
        version = self._generate_version(model_dir)
        metadata.version = version

        # Create version directory
        version_dir = model_dir / version
        version_dir.mkdir(parents=True, exist_ok=True)

        # Save model
        model_path = version_dir / "model.joblib"
        joblib.dump(model, model_path)

        # Save scaler
        scaler_path = version_dir / "scaler.joblib"
        joblib.dump(scaler, scaler_path)

        # Save metadata
        metadata_path = version_dir / "metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(asdict(metadata), f, indent=2)

        # Update "latest" pointer
        self._update_latest(model_dir, version)

        print(f"[MODEL] Saved {sport.upper()} {prop_type} @ {line} as {version}")
        print(f"        Location: {version_dir}")

        return version

    def load_model(
        self,
        sport: str,
        prop_type: str,
        line: float,
        version: str = "latest"
    ) -> Tuple[object, object, ModelMetadata]:
        """
        Load a trained model with its scaler and metadata.

        Args:
            sport: 'nhl' or 'nba'
            prop_type: 'points', 'shots', etc.
            line: Betting line
            version: Specific version or "latest"

        Returns:
            Tuple of (model, scaler, metadata)

        Raises:
            FileNotFoundError: If no model exists for the combination
        """
        model_dir = self._get_model_dir(sport, prop_type, line)

        if version == "latest":
            version = self._get_latest_version(model_dir)
            if version is None:
                raise FileNotFoundError(
                    f"No models found for {sport} {prop_type} @ {line}"
                )

        version_dir = model_dir / version

        if not version_dir.exists():
            raise FileNotFoundError(
                f"Model version {version} not found for {sport} {prop_type} @ {line}"
            )

        # Load model
        model = joblib.load(version_dir / "model.joblib")

        # Load scaler
        scaler = joblib.load(version_dir / "scaler.joblib")

        # Load metadata
        with open(version_dir / "metadata.json", 'r') as f:
            metadata_dict = json.load(f)
            metadata = ModelMetadata(**metadata_dict)

        return model, scaler, metadata

    def is_model_available(self, sport: str, prop_type: str, line: float) -> bool:
        """Check if a model exists for the given combination"""
        model_dir = self._get_model_dir(sport, prop_type, line)
        return self._get_latest_version(model_dir) is not None

    def get_model_stats(self, sport: str, prop_type: str, line: float) -> Dict:
        """Get stats for a model without loading the full model"""
        model_dir = self._get_model_dir(sport, prop_type, line)
        version = self._get_latest_version(model_dir)

        if version is None:
            return {}

        metadata_path = model_dir / version / "metadata.json"
        if not metadata_path.exists():
            return {}

        with open(metadata_path, 'r') as f:
            return json.load(f)

    def list_models(self, sport: str = None) -> List[Dict]:
        """
        List all available models.

        Args:
            sport: Optional filter by sport ('nhl' or 'nba')

        Returns:
            List of model info dicts
        """
        models = []

        sports = [sport.lower()] if sport else ['nhl', 'nba']

        for s in sports:
            sport_dir = self.registry_dir / s
            if not sport_dir.exists():
                continue

            for prop_dir in sport_dir.iterdir():
                if not prop_dir.is_dir():
                    continue

                version = self._get_latest_version(prop_dir)
                if not version:
                    continue

                # Parse prop_type and line from directory name
                # e.g., "points_0_5" -> prop_type="points", line=0.5
                parts = prop_dir.name.rsplit('_', 2)
                if len(parts) >= 3:
                    prop_type = parts[0]
                    line = float(f"{parts[1]}.{parts[2]}")
                else:
                    # Fallback for names like "shots_1_5"
                    prop_type = parts[0]
                    line = float(parts[1].replace('_', '.'))

                stats = self.get_model_stats(s, prop_type, line)
                models.append({
                    'sport': s.upper(),
                    'prop_type': prop_type,
                    'line': line,
                    'version': version,
                    'model_type': stats.get('model_type', 'unknown'),
                    'test_accuracy': stats.get('test_accuracy'),
                    'test_roc_auc': stats.get('test_roc_auc'),
                    'test_brier_score': stats.get('test_brier_score'),
                    'trained_at': stats.get('trained_at')
                })

        return models

    def delete_model(self, sport: str, prop_type: str, line: float, version: str = None):
        """
        Delete a model version or all versions for a prop/line.

        Args:
            sport: 'nhl' or 'nba'
            prop_type: 'points', 'shots', etc.
            line: Betting line
            version: Specific version to delete, or None for all
        """
        import shutil

        model_dir = self._get_model_dir(sport, prop_type, line)

        if version:
            # Delete specific version
            version_dir = model_dir / version
            if version_dir.exists():
                shutil.rmtree(version_dir)
                print(f"[MODEL] Deleted {sport} {prop_type} @ {line} version {version}")

                # Update latest pointer if needed
                current_latest = self._get_latest_version(model_dir)
                if current_latest == version:
                    # Find new latest
                    versions = [d.name for d in model_dir.iterdir()
                               if d.is_dir() and d.name.startswith('v')]
                    if versions:
                        new_latest = sorted(versions)[-1]
                        self._update_latest(model_dir, new_latest)
                    else:
                        # No versions left, remove latest.txt
                        latest_file = model_dir / "latest.txt"
                        if latest_file.exists():
                            latest_file.unlink()
        else:
            # Delete all versions
            if model_dir.exists():
                shutil.rmtree(model_dir)
                print(f"[MODEL] Deleted all versions for {sport} {prop_type} @ {line}")

    def _generate_version(self, model_dir: Path) -> str:
        """Generate a new version string based on date and increment"""
        date_str = datetime.now().strftime('%Y%m%d')

        # Find existing versions for today
        existing = []
        if model_dir.exists():
            existing = [d.name for d in model_dir.iterdir()
                       if d.is_dir() and d.name.startswith(f'v{date_str}')]

        if not existing:
            return f"v{date_str}_001"

        # Increment from highest existing
        max_num = max(int(v.split('_')[1]) for v in existing)
        return f"v{date_str}_{max_num + 1:03d}"

    def _get_latest_version(self, model_dir: Path) -> Optional[str]:
        """Get the latest version in a model directory"""
        latest_file = model_dir / "latest.txt"

        if latest_file.exists():
            version = latest_file.read_text().strip()
            # Verify the version directory exists
            if (model_dir / version).exists():
                return version

        # Fallback: find most recent version directory
        if not model_dir.exists():
            return None

        versions = [d.name for d in model_dir.iterdir()
                   if d.is_dir() and d.name.startswith('v')]
        if versions:
            return sorted(versions)[-1]

        return None

    def _update_latest(self, model_dir: Path, version: str):
        """Update the latest version pointer"""
        latest_file = model_dir / "latest.txt"
        latest_file.write_text(version)


def print_registry_summary(registry: ModelRegistry = None):
    """Print a summary of all models in the registry"""
    if registry is None:
        registry = ModelRegistry()

    models = registry.list_models()

    if not models:
        print("No models found in registry.")
        return

    print("\n" + "=" * 70)
    print("ML MODEL REGISTRY SUMMARY")
    print("=" * 70)

    for sport in ['NHL', 'NBA']:
        sport_models = [m for m in models if m['sport'] == sport]
        if not sport_models:
            continue

        print(f"\n{sport}:")
        print("-" * 60)
        print(f"{'Prop':<12} {'Line':<8} {'Model':<18} {'Accuracy':<10} {'ROC-AUC':<10}")
        print("-" * 60)

        for m in sorted(sport_models, key=lambda x: (x['prop_type'], x['line'])):
            acc = f"{m['test_accuracy']:.1%}" if m['test_accuracy'] else "N/A"
            auc = f"{m['test_roc_auc']:.3f}" if m['test_roc_auc'] else "N/A"
            print(f"{m['prop_type']:<12} {m['line']:<8} {m['model_type']:<18} {acc:<10} {auc:<10}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    # Test the registry
    registry = ModelRegistry()
    print_registry_summary(registry)
