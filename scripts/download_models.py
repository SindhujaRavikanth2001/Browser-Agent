import os
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, AutoProcessor, AutoModelForVision2Seq
from app.logger import logger

def download_models():
    """Download and cache the required HuggingFace models."""
    # Enable downloads & set cache location
    os.environ["TRANSFORMERS_OFFLINE"] = "0"
    os.environ["HF_HOME"] = "/ephemeral/.cache/huggingface"
    
    cache_dir = "/ephemeral/.cache/huggingface"
    os.makedirs(cache_dir, exist_ok=True)
    
    # 4-bit quantization settings
    quantization_config = {
        "load_in_4bit": True,
        "bnb_4bit_compute_dtype": torch.float16,
        "bnb_4bit_quant_type": "nf4",
        "bnb_4bit_use_double_quant": True,
    }
    
    models = [
        {
            "name": "Qwen/Qwen-7B-Chat",    
            "type": "causal"
        },
        {
            "name": "Salesforce/blip2-flan-t5-xl",
            "type": "vision"
        }
    ]
    
    for info in models:
        model_name = info["name"]
        model_type = info["type"]
        logger.info(f"Downloading model: {model_name}")
        try:
            if model_type == "causal":
                # Download & quantize the chat model
                AutoModelForCausalLM.from_pretrained(
                    model_name,
                    cache_dir=cache_dir,
                    quantization_config=quantization_config,
                    device_map="auto",
                    trust_remote_code=True
                )
                AutoTokenizer.from_pretrained(
                    model_name,
                    cache_dir=cache_dir,
                    trust_remote_code=True
                )
            else:  # vision
                AutoModelForVision2Seq.from_pretrained(
                    model_name,
                    cache_dir=cache_dir,
                    device_map="auto",
                    trust_remote_code=True
                )
                AutoProcessor.from_pretrained(
                    model_name,
                    cache_dir=cache_dir,
                    trust_remote_code=True
                )
            
            logger.info(f"Successfully downloaded and cached {model_name}")
        except Exception as e:
            logger.error(f"Error downloading {model_name}: {e}")
            raise

if __name__ == "__main__":
    download_models()
