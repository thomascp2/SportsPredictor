"""
NHL V2 Feature Extractors Package

Binary Feature Extractor: For points O0.5 predictions (binary classification)
Continuous Feature Extractor: For shots O2.5+ predictions (regression)

Version: 2.0
Date: 2025-11-08
"""

from .binary_feature_extractor import BinaryFeatureExtractor
from .continuous_feature_extractor import ContinuousFeatureExtractor

__all__ = ['BinaryFeatureExtractor', 'ContinuousFeatureExtractor']