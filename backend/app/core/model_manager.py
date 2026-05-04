"""
Model Manager - Automatic model downloading and caching for ML models.
Handles downloading and caching of models like YOLO and sentence transformers.
"""

import os
import logging
from pathlib import Path
from typing import Any, Callable, List, Optional
import requests
import shutil
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
        manager = get_model_manager()
        model_path = manager.get_yolo_model_path(model_name)

        # Keep a local backend copy under backend/models for deterministic startup behavior.
        if not model_path.exists():
            try:
                from ultralytics.utils.downloads import attempt_download_asset

                downloaded_path = Path(attempt_download_asset(model_name))
                if downloaded_path.exists():
                    if downloaded_path.resolve() != model_path.resolve():
                        model_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(downloaded_path), str(model_path))
                    logger.info(f"YOLO model cached locally at: {model_path}")
            except Exception as dl_exc:
                logger.warning(f"Could not pre-cache YOLO model locally: {dl_exc}")

        model = YOLO(str(model_path) if model_path.exists() else model_name)
        return model
    except Exception as e:
        logger.error(f"Failed to load YOLO model: {e}")
        raise


def _narrator_return(text: str) -> List[dict]:
    """Match HuggingFace pipeline output shape expected by reports._generate_with_local_narrator."""
    return [{"generated_text": (text or "").strip()}]


def _build_seq2seq_narrator(model: Any, tokenizer: Any) -> Callable[..., List[dict]]:
    """T5 / FLAN-T5 / BART-style: use generate() (pipeline task text2text-generation was removed in newer transformers)."""
    import torch

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)
    model.eval()

    def narrate(
        prompt: str,
        max_new_tokens: int = 280,
        do_sample: bool = True,
        temperature: float = 0.5,
        **_kwargs: Any,
    ) -> List[dict]:
        enc = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
        enc = {k: v.to(device) for k, v in enc.items()}
        with torch.no_grad():
            out_ids = model.generate(
                **enc,
                max_new_tokens=max_new_tokens,
                do_sample=do_sample,
                temperature=max(float(temperature), 1e-5),
                top_p=0.92,
            )
        in_len = enc["input_ids"].shape[1]
        gen_ids = out_ids[0][in_len:]
        text = tokenizer.decode(gen_ids, skip_special_tokens=True).strip()
        return _narrator_return(text)

    return narrate


def _format_instruct_prompt(tokenizer: Any, user_text: str) -> str:
    """Use chat template when the tokenizer defines one (Qwen/Llama/Mistral instruct checkpoints)."""
    if getattr(tokenizer, "chat_template", None):
        try:
            messages = [{"role": "user", "content": user_text}]
            return tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception:
            pass
    return user_text


def _build_causal_narrator(model: Any, tokenizer: Any) -> Callable[..., List[dict]]:
    """Decoder-only (Llama, Qwen, GPT-2, …): causal LM generation."""
    import torch

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)
    model.eval()
    if getattr(tokenizer, "pad_token", None) is None:
        tokenizer.pad_token = tokenizer.eos_token

    def narrate(
        prompt: str,
        max_new_tokens: int = 280,
        do_sample: bool = True,
        temperature: float = 0.5,
        **_kwargs: Any,
    ) -> List[dict]:
        formatted = _format_instruct_prompt(tokenizer, prompt)
        enc = tokenizer(formatted, return_tensors="pt", truncation=True, max_length=4096)
        enc = {k: v.to(device) for k, v in enc.items()}
        with torch.no_grad():
            out_ids = model.generate(
                **enc,
                max_new_tokens=max_new_tokens,
                do_sample=do_sample,
                temperature=max(float(temperature), 1e-5),
                top_p=0.92,
                pad_token_id=getattr(tokenizer, "pad_token_id", None),
                eos_token_id=getattr(tokenizer, "eos_token_id", None),
            )
        in_len = enc["input_ids"].shape[1]
        gen_ids = out_ids[0][in_len:]
        text = tokenizer.decode(gen_ids, skip_special_tokens=True).strip()
        return _narrator_return(text)

    return narrate


def ensure_local_narrative_pipeline(model_name: str = "Qwen/Qwen2.5-1.5B-Instruct"):
    """
    Download and return a callable that behaves like a HF pipeline for narrative text.

    Newer ``transformers`` versions no longer register ``text2text-generation`` as a pipeline
    task name; we load seq2seq or causal models explicitly and call ``generate()``, same as
    typical offline inference (similar idea to bundling YOLO weights locally).
    """
    try:
        from transformers import (
            AutoConfig,
            AutoModelForCausalLM,
            AutoModelForSeq2SeqLM,
            AutoTokenizer,
        )

        manager = get_model_manager()
        cache_dir = manager.cache_dir / "local_narrative" / model_name.replace("/", "--")
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_kw = {"cache_dir": str(cache_dir)}

        config = AutoConfig.from_pretrained(model_name, **cache_kw)
        model_type = (getattr(config, "model_type", "") or "").lower()
        arch0 = ""
        if getattr(config, "architectures", None) and isinstance(config.architectures, list):
            arch0 = str(config.architectures[0] or "").lower()

        seq2seq_types = {"t5", "mt5", "bart", "pegasus", "mbart", "marian", "led", "blenderbot"}
        causal_types = {
            "llama",
            "mistral",
            "qwen2",
            "qwen3",
            "gemma",
            "gpt2",
            "gpt_neo",
            "gpt_neox",
            "gptj",
            "phi",
            "phi3",
            "opt",
            "falcon",
            "stablelm",
        }

        tokenizer = AutoTokenizer.from_pretrained(model_name, **cache_kw)

        if model_type in seq2seq_types or any(a in arch0 for a in ("t5", "bart", "pegasus", "mbart", "marian")):
            model = AutoModelForSeq2SeqLM.from_pretrained(model_name, **cache_kw)
            narrator = _build_seq2seq_narrator(model, tokenizer)
            logger.info(
                "Local narrative model ready (seq2seq/generate): %s (cache: %s)",
                model_name,
                cache_dir,
            )
            return narrator

        if model_type in causal_types or any(
            a in arch0 for a in ("llama", "mistral", "qwen", "gemma", "gpt", "phi", "opt", "falcon")
        ):
            model = AutoModelForCausalLM.from_pretrained(model_name, **cache_kw)
            narrator = _build_causal_narrator(model, tokenizer)
            logger.info(
                "Local narrative model ready (causal LM/generate): %s (cache: %s)",
                model_name,
                cache_dir,
            )
            return narrator

        # Fallback: try seq2seq (many hub models still load as Seq2SeqLM even if model_type string varies)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_name, **cache_kw)
        narrator = _build_seq2seq_narrator(model, tokenizer)
        logger.info(
            "Local narrative model ready (seq2seq fallback): %s (cache: %s)",
            model_name,
            cache_dir,
        )
        return narrator
    except Exception as e:
        logger.error(f"Failed to load local narrative model: {e}")
        raise
