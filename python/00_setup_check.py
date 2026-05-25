"""
Environment sanity check. Run after installing requirements + the CUDA torch build:
    python python/00_setup_check.py
Confirms the imports the pipeline needs and whether a GPU is visible.
"""
import importlib, sys

print(f"Python: {sys.version.split()[0]}")

mods = ["numpy", "pandas", "pyarrow", "datasets", "transformers",
        "accelerate", "sklearn", "tqdm"]
for m in mods:
    try:
        mod = importlib.import_module(m)
        print(f"  [ok] {m} {getattr(mod, '__version__', '?')}")
    except Exception as e:
        print(f"  [MISSING] {m}: {e}")

# torch + CUDA (the part that matters for training/inference speed)
try:
    import torch
    print(f"  [ok] torch {torch.__version__}")
    print(f"       cuda available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"       device: {torch.cuda.get_device_name(0)}")
        print(f"       VRAM (GB): {torch.cuda.get_device_properties(0).total_memory/1e9:.1f}")
    else:
        print("       WARNING: no GPU visible — install the CUDA torch wheel "
              "(see requirements.txt). CPU works but is far slower.")
except Exception as e:
    print(f"  [MISSING] torch: {e}")

# LLM labeling client (optional; only one is needed)
for m in ["google.generativeai", "anthropic"]:
    try:
        importlib.import_module(m)
        print(f"  [ok] labeler available: {m}")
    except Exception:
        print(f"  [note] labeler not installed: {m}")
