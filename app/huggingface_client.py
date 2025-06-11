import os
import glob
from typing import List, Optional, Union, Dict, Any
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, AutoProcessor, AutoModelForVision2Seq, BitsAndBytesConfig
from app.logger import logger
import traceback
import asyncio

class HuggingFaceClient:
    def __init__(self, model_name: str):
        logger.info(f"HuggingFaceClient __init__ entered for model: {model_name}")
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        self.processor = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        try:
            self._load_model()
        except Exception as e:
            logger.error(f"Failed to load model {model_name}: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Cleanup any partially loaded resources
            self._cleanup()
            raise

    def _cleanup(self):
        """Clean up model resources"""
        if hasattr(self, 'model') and self.model is not None:
            del self.model
            self.model = None
        if hasattr(self, 'tokenizer') and self.tokenizer is not None:
            del self.tokenizer
            self.tokenizer = None
        if hasattr(self, 'processor') and self.processor is not None:
            del self.processor
            self.processor = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _load_model(self):
        """Load the model and tokenizer with proper error handling."""
        try:
            # Get model path from cache
            model_path = self._get_model_path()
            logger.info(f"Using model from path: {model_path}")
            
            # Check GPU memory
            gpu_memory_gb = 0
            if torch.cuda.is_available():
                gpu_memory = torch.cuda.get_device_properties(0).total_memory
                gpu_memory_gb = gpu_memory / (1024**3)
                logger.info(f"Available GPU memory: {gpu_memory_gb:.2f}GB")
            
            # Load tokenizer first
            logger.info("Loading tokenizer...")
            self.tokenizer = AutoTokenizer.from_pretrained(
                model_path,
                trust_remote_code=True,
                use_fast=False,
                local_files_only=True
            )
            
            # Configure quantization and device mapping
            device_map = "auto"
            model_kwargs = {
                "trust_remote_code": True,
                "torch_dtype": torch.float16,
                "low_cpu_mem_usage": True,
                "local_files_only": True
            }
            
            # For large models like 72B, use aggressive memory management
            if "72B" in self.model_name or gpu_memory_gb < 48:
                logger.info("Using aggressive memory management for large model")
                
                # Configure 4-bit quantization with CPU offloading
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                    llm_int8_enable_fp32_cpu_offload=True
                )
                
                # Set memory limits to force CPU offloading
                if gpu_memory_gb > 0:
                    max_gpu_memory = f"{int(gpu_memory_gb * 0.7)}GiB"  # Use 70% of GPU memory
                    max_memory = {0: max_gpu_memory, "cpu": "30GiB"}
                    logger.info(f"Setting max GPU memory to {max_gpu_memory}")
                else:
                    max_memory = {"cpu": "30GiB"}
                    device_map = "cpu"
                
                model_kwargs.update({
                    "quantization_config": quantization_config,
                    "device_map": device_map,
                    "max_memory": max_memory
                })
            
            elif gpu_memory_gb >= 48:
                # For systems with plenty of GPU memory
                logger.info("Using standard GPU loading")
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True
                )
                model_kwargs.update({
                    "quantization_config": quantization_config,
                    "device_map": device_map
                })
            
            # Load model with error handling
            logger.info(f"Loading model from {model_path}")
            try:
                self.model = AutoModelForCausalLM.from_pretrained(
                    model_path,
                    **model_kwargs
                )
                logger.info("Model loaded successfully")
                
                # Log device placement if available
                if hasattr(self.model, 'hf_device_map'):
                    logger.info(f"Model device map: {self.model.hf_device_map}")
                
            except torch.cuda.OutOfMemoryError as oom_e:
                logger.error(f"GPU OOM during model loading: {oom_e}")
                # Try CPU-only fallback
                logger.info("Attempting CPU-only fallback...")
                torch.cuda.empty_cache()
                
                model_kwargs_cpu = {
                    "trust_remote_code": True,
                    "torch_dtype": torch.float16,
                    "device_map": "cpu",
                    "local_files_only": True
                }
                
                self.model = AutoModelForCausalLM.from_pretrained(
                    model_path,
                    **model_kwargs_cpu
                )
                logger.info("Model loaded successfully on CPU")
                
        except Exception as e:
            logger.error(f"Error in _load_model: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

    def _get_model_path(self) -> str:
        """Get the local path of the model."""
        # Use the ephemeral directory for model storage
        cache_dir = "/ephemeral/.cache/huggingface"
        model_path = os.path.join(
            cache_dir,
            "hub",
            f"models--{self.model_name.replace('/', '--')}",
            "snapshots",
            "495f39366efef23836d0cfae4fbe635880d2be31"  # Specific commit hash
        )
        
        if not os.path.exists(model_path):
            raise ValueError(f"Model path does not exist: {model_path}")
            
        return model_path

    def generate_text(self, prompt: str, max_length: int = 2048, temperature: float = 0.7) -> str:
        """Generate text from the model (synchronous version)."""
        if not self.model or not self.tokenizer:
            raise RuntimeError("Model or tokenizer not loaded")
        
        # Handle tokenizer padding
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        
        try:
            # Tokenize input
            inputs = self.tokenizer(prompt, return_tensors="pt")
            
            # Move inputs to appropriate device
            if hasattr(self.model, 'parameters'):
                first_param_device = next(self.model.parameters()).device
                inputs = {k: v.to(first_param_device) for k, v in inputs.items()}
            
            # Configure generation parameters
            generation_kwargs = {
                "max_new_tokens": min(max_length, 512),  # Limit max tokens to prevent OOM
                "temperature": temperature,
                "do_sample": temperature > 0.0,
                "pad_token_id": self.tokenizer.eos_token_id,
                "eos_token_id": self.tokenizer.eos_token_id,
                "use_cache": True
            }
            
            if temperature > 0.0:
                generation_kwargs.update({
                    "top_k": 50,
                    "top_p": 0.9
                })
            
            # Generate with memory management
            with torch.no_grad():
                try:
                    outputs = self.model.generate(
                        **inputs,
                        **generation_kwargs
                    )
                except torch.cuda.OutOfMemoryError:
                    logger.warning("GPU OOM during generation, trying with shorter output...")
                    torch.cuda.empty_cache()
                    generation_kwargs["max_new_tokens"] = min(50, max_length)
                    outputs = self.model.generate(
                        **inputs,
                        **generation_kwargs
                    )
            
            # Decode only the generated part
            generated_text = self.tokenizer.decode(
                outputs[0][inputs['input_ids'].shape[1]:], 
                skip_special_tokens=True
            )
            return generated_text.strip()
            
        except Exception as e:
            logger.error(f"Error in generate_text: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

    async def generate_text_async(self, prompt: str, max_length: int = 2048, temperature: float = 0.7) -> str:
        """Async wrapper for generate_text."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, 
            self.generate_text, 
            prompt, 
            max_length, 
            temperature
        )

    async def generate_image_caption(self, image_path: str) -> str:
        """Generate caption for an image using BLIP2 model"""
        try:
            if "blip2" in self.model_name.lower():
                from PIL import Image
                image = Image.open(image_path)
                inputs = self.processor(image, return_tensors="pt")
                
                # Move to appropriate device
                if hasattr(self.model, 'parameters'):
                    first_param_device = next(self.model.parameters()).device
                    inputs = {k: v.to(first_param_device) for k, v in inputs.items()}
                
                with torch.no_grad():
                    outputs = self.model.generate(**inputs)
                caption = self.processor.decode(outputs[0], skip_special_tokens=True)
                return caption
            else:
                raise ValueError(f"Model {self.model_name} does not support image captioning")
        except Exception as e:
            logger.error(f"Error generating image caption: {str(e)}")
            raise

    def process_image(self, image_path: str, prompt: str) -> str:
        """Process an image with the model."""
        try:
            if not self.processor:
                if "blip2" in self.model_name.lower():
                    model_path = self._get_model_path()
                    self.processor = AutoProcessor.from_pretrained(
                        model_path,
                        local_files_only=True,
                        trust_remote_code=True
                    )
                else:
                    raise ValueError(f"No processor available for model {self.model_name}")
            
            inputs = self.processor(images=image_path, text=prompt, return_tensors="pt")
            
            # Move to appropriate device
            if hasattr(self.model, 'parameters'):
                first_param_device = next(self.model.parameters()).device
                inputs = {k: v.to(first_param_device) for k, v in inputs.items()}
            
            with torch.no_grad():
                outputs = self.model.generate(**inputs)
            return self.processor.decode(outputs[0], skip_special_tokens=True)
            
        except Exception as e:
            logger.error(f"Error in process_image: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

    def __del__(self):
        """Cleanup method to free GPU memory"""
        try:
            self._cleanup()
        except Exception:
            pass  # Ignore cleanup errors during destruction