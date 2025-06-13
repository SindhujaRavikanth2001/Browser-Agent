import os
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, AutoProcessor, AutoModelForVision2Seq
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
    
    # List of models to download with their types
    models = [
        {
            "name": "Qwen/Qwen2.5-72B-Instruct",
            "type": "causal"
        },
        {
            "name": "Salesforce/blip2-flan-t5-xl",
            "type": "vision"
        }
    ]
    
    for model_info in models:
        model_name = model_info["name"]
        model_type = model_info["type"]
        logger.info(f"Downloading model: {model_name}")
        try:
            if model_type == "causal":
                # Download and cache the causal model
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
            elif model_type == "vision":
                # Download and cache the vision model
                model = AutoModelForVision2Seq.from_pretrained(
                    model_name,
                    cache_dir=cache_dir,
                    device_map="auto",
                    trust_remote_code=True
                )
                
                # Download and cache the processor
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