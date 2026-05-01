"""
Model Manager - Automatic model downloading and caching for ML models.
Handles downloading and caching of models like YOLO and sentence transformers.
"""

import os
import logging
from pathlib import Path
from typing import Optional
import requests
from urllib.parse import urlparse
from tqdm import tqdm

logger = logging.getLogger(__name__)

class ModelManager:
    """Manages automatic downloading and caching of ML models."""
    
    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize model manager with cache directory."""
        if cache_dir is None:
            # Default cache directory in backend/models
            self.cache_dir = Path(__file__).parent.parent.parent / "models"
        else:
            self.cache_dir = cache_dir
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Model cache directory: {self.cache_dir}")
    
    def download_file(self, url: str, filename: str, show_progress: bool = True) -> Path:
        """Download a file from URL to cache directory with progress bar."""
        file_path = self.cache_dir / filename
        
        # Check if file already exists
        if file_path.exists():
            logger.info(f"Model already cached: {file_path}")
            return file_path
        
        logger.info(f"Downloading model from {url} to {file_path}")
        
        try:
            # Stream download with progress bar
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            
            with open(file_path, 'wb') as f:
                if show_progress:
                    with tqdm(total=total_size, unit='B', unit_scale=True, desc=filename) as pbar:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                pbar.update(len(chunk))
                else:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            
            logger.info(f"Model downloaded successfully: {file_path}")
            return file_path
            
        except Exception as e:
            # Clean up partial download
            if file_path.exists():
                file_path.unlink()
            logger.error(f"Failed to download model: {e}")
            raise
    
    def get_sentence_transformer_model(self, model_name: str = "all-MiniLM-L6-v2") -> Path:
        """
        Get or download sentence transformer model.
        Returns the path to the cached model directory.
        """
        model_cache_dir = self.cache_dir / f"sentence-transformers-{model_name}"
        
        if model_cache_dir.exists():
            logger.info(f"Sentence transformer model already cached: {model_cache_dir}")
            return model_cache_dir
        
        logger.info(f"Setting up sentence transformer model: {model_name}")
        
        try:
            from sentence_transformers import SentenceTransformer
            
            # Download and cache the model using sentence-transformers' built-in caching
            model = SentenceTransformer(
                model_name,
                cache_folder=str(model_cache_dir)
            )
            
            # Test the model to ensure it's properly loaded
            test_embedding = model.encode("test")
            logger.info(f"Model loaded successfully, embedding shape: {test_embedding.shape}")
            
            return model_cache_dir
            
        except ImportError:
            logger.error("sentence-transformers package not installed")
            raise ImportError("Please install sentence-transformers: pip install sentence-transformers")
        except Exception as e:
            logger.error(f"Failed to load sentence transformer model: {e}")
            raise
    
    def get_yolo_model_path(self, model_name: str = "yolov8n.pt") -> Path:
        """Get or download YOLO model."""
        model_path = self.cache_dir / model_name
        
        if model_path.exists():
            logger.info(f"YOLO model already cached: {model_path}")
            return model_path
        
        # YOLO models are downloaded automatically by ultralytics
        # But we can ensure they're in our cache directory
        logger.info(f"YOLO model will be downloaded by ultralytics: {model_name}")
        return model_path

# Global model manager instance
_model_manager = None

def get_model_manager() -> ModelManager:
    """Get global model manager instance."""
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager

def ensure_sentence_transformer_model(model_name: str = "all-MiniLM-L6-v2"):
    """
    Ensure sentence transformer model is downloaded and available.
    Returns the model instance ready for use.
    """
    manager = get_model_manager()
    model_cache_dir = manager.get_sentence_transformer_model(model_name)
    
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(
            model_name,
            cache_folder=str(model_cache_dir)
        )
        return model
    except Exception as e:
        logger.error(f"Failed to load sentence transformer model: {e}")
        raise

def ensure_yolo_model(model_name: str = "yolov8n.pt"):
    """
    Ensure YOLO model is available.
    Returns the model instance ready for use.
    """
    try:
        from ultralytics import YOLO
        model = YOLO(model_name)
        return model
    except Exception as e:
        logger.error(f"Failed to load YOLO model: {e}")
        raise
