"""
ML Training Module for Sports Predictions
==========================================

This module provides:
- Model training pipeline (train_models.py)
- Model persistence and registry (model_manager.py)
- Production inference (production_predictor.py)
"""

from .model_manager import ModelRegistry, ModelMetadata
from .production_predictor import ProductionPredictor

__all__ = ['ModelRegistry', 'ModelMetadata', 'ProductionPredictor']
