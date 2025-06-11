import os
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, AutoProcessor
from app.logger import logger

def download_models():
    """Download and cache the required HuggingFace models."""
    # Set environment variables for offline mode
    os.environ["TRANSFORMERS_OFFLINE"] = "0"  # Enable downloads
    os.environ["HF_HOME"] = "/ephemeral/.cache/huggingface"
    
    # Create cache directory if it doesn't exist
    cache_dir = "/ephemeral/.cache/huggingface"
    os.makedirs(cache_dir, exist_ok=True)
    
    # Configure 4-bit quantization
    quantization_config = {
        "load_in_4bit": True,
        "bnb_4bit_compute_dtype": torch.float16,
        "bnb_4bit_quant_type": "nf4",
        "bnb_4bit_use_double_quant": True
    }
    
    # List of models to download
    models = [
        "Qwen/Qwen2.5-72B-Instruct",
        "Salesforce/blip2-flan-t5-xl"
    ]
    
    for model_name in models:
        logger.info(f"Downloading model: {model_name}")
        try:
            # Download and cache the model
            model = AutoModelForCausalLM.from_pretrained(
                model_name,
                cache_dir=cache_dir,
                quantization_config=quantization_config,
                device_map="auto",
                trust_remote_code=True
            )
            
            # Download and cache the tokenizer
            tokenizer = AutoTokenizer.from_pretrained(
                model_name,
                cache_dir=cache_dir,
                trust_remote_code=True
            )
            
            # For BLIP2 model, also download the processor
            if "blip2" in model_name.lower():
                processor = AutoProcessor.from_pretrained(
                    model_name,
                    cache_dir=cache_dir,
                    trust_remote_code=True
                )
            
            logger.info(f"Successfully downloaded and cached {model_name}")
            
        except Exception as e:
            logger.error(f"Error downloading {model_name}: {str(e)}")
            raise

if __name__ == "__main__":
    download_models() 