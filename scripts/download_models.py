import os
import sys
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, AutoProcessor, AutoModelForVision2Seq
from app.logger import logger

# ensure project root is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def download_models():
    # Enable downloads & set cache location
    os.environ["TRANSFORMERS_OFFLINE"] = "0"
    os.environ["HF_HOME"] = "/mnt/data/browseragent_llm"

    cache_dir = os.environ["HF_HOME"]
    os.makedirs(cache_dir, exist_ok=True)

    # 4-bit quantization settings for causal models
    quantization_config = {
        "load_in_4bit": True,
        "bnb_4bit_compute_dtype": torch.float16,
        "bnb_4bit_quant_type": "nf4",
        "bnb_4bit_use_double_quant": True,
    }

    models = [
        {"name": "Qwen/Qwen-7B-Chat", "type": "causal"},
        {"name": "microsoft/Phi-3.5-mini-instruct", "type": "causal"},
        {"name": "Salesforce/blip2-flan-t5-xl", "type": "vision"},
        {"name": "Qwen/Qwen2.5-72B-Instruct", "type": "causal"}
    ]

    for info in models:
        model_name, model_type = info["name"], info["type"]
        logger.info(f"Downloading model: {model_name}")

        try:
            if model_type == "causal":
                AutoModelForCausalLM.from_pretrained(
                    model_name,
                    cache_dir=cache_dir,
                    quantization_config=quantization_config,
                    device_map="auto",
                    trust_remote_code=True,
                    offload_folder=cache_dir,        # allow offloading if needed
                    offload_state_dict=True,
                    low_cpu_mem_usage=True
                )
                AutoTokenizer.from_pretrained(
                    model_name,
                    cache_dir=cache_dir,
                    trust_remote_code=True
                )

            else:  # vision model
                # build a max_memory map for each GPU, leaving ~2 GB free per card
                num_gpus = torch.cuda.device_count()
                max_memory = {
                    i: f"{int(torch.cuda.get_device_properties(i).total_memory / 2**30) - 2}GB"
                    for i in range(num_gpus)
                }

                AutoModelForVision2Seq.from_pretrained(
                    model_name,
                    cache_dir=cache_dir,
                    device_map="auto",
                    max_memory=max_memory,
                    offload_folder=cache_dir,
                    offload_state_dict=True,
                    trust_remote_code=True,
                    low_cpu_mem_usage=True
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
