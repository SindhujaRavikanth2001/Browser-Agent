#!/usr/bin/env python3
"""
Quick test to check if Qwen2.5-72B can load with your current setup
"""
import torch
import os
from transformers import AutoConfig

def test_model_loading():
    print("🔍 Quick GPU Memory Test for Qwen2.5-72B")
    print("=" * 50)
    
    # Check GPU
    if torch.cuda.is_available():
        gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
        gpu_name = torch.cuda.get_device_name(0)
        print(f"GPU: {gpu_name}")
        print(f"GPU Memory: {gpu_memory:.1f} GB")
        
        # Clear any existing cache
        torch.cuda.empty_cache()
        
        # Check available memory
        allocated = torch.cuda.memory_allocated(0) / 1024**3
        cached = torch.cuda.memory_reserved(0) / 1024**3
        free = gpu_memory - cached
        
        print(f"Available: {free:.1f} GB")
        print()
        
        # Recommendations based on memory
        if gpu_memory < 16:
            print("❌ Insufficient GPU memory for Qwen2.5-72B")
            print("💡 Recommendation: Use CPU-only or smaller model")
            return False
        elif gpu_memory < 24:
            print("⚠️  Limited GPU memory - will need heavy CPU offloading")
            print("💡 Recommendation: Use CPU/GPU hybrid with max_memory settings")
        elif gpu_memory < 48:
            print("✅ Should work with 4-bit quantization and some CPU offloading")
        else:
            print("✅ Plenty of memory for 4-bit quantized model")
        
        return True
    else:
        print("❌ No GPU available - will use CPU only")
        return False

def test_model_config():
    """Test if we can at least load the model config"""
    print("\n🧪 Testing model config loading...")
    
    model_path = "/ephemeral/.cache/huggingface/hub/models--Qwen--Qwen2.5-72B-Instruct/snapshots/495f39366efef23836d0cfae4fbe635880d2be31"
    
    try:
        config = AutoConfig.from_pretrained(model_path, local_files_only=True)
        print(f"✅ Model config loaded successfully")
        print(f"   Model type: {config.model_type}")
        print(f"   Hidden size: {config.hidden_size}")
        print(f"   Num layers: {config.num_hidden_layers}")
        print(f"   Vocab size: {config.vocab_size}")
        
        # Estimate memory requirements
        params = config.num_hidden_layers * config.hidden_size * config.hidden_size
        estimated_memory_fp16 = params * 2 / 1024**3  # 2 bytes per parameter for fp16
        estimated_memory_4bit = params * 0.5 / 1024**3  # 0.5 bytes per parameter for 4-bit
        
        print(f"\n📊 Estimated memory requirements:")
        print(f"   FP16: {estimated_memory_fp16:.1f} GB")
        print(f"   4-bit quantized: {estimated_memory_4bit:.1f} GB")
        
        return True
        
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        return False

if __name__ == "__main__":
    gpu_ok = test_model_loading()
    config_ok = test_model_config()
    
    print("\n" + "=" * 50)
    if gpu_ok and config_ok:
        print("🎉 Model should load with the fixed HuggingFace client!")
        print("\n💡 Next steps:")
        print("1. Replace your huggingface_client.py with the fixed version")
        print("2. Update the LLM ask method to use generate_text_async")
        print("3. Fix the BrowserUseTool __del__ method")
        print("4. Test with a simple message")
    else:
        print("⚠️  There may be issues. Consider:")
        print("1. Using a smaller model (Qwen2.5-14B or Qwen2.5-7B)")
        print("2. Running in CPU-only mode")
        print("3. Using cloud GPUs with more memory")