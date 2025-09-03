"""
Local LLM utilities for optional theme summarization.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, Optional, Tuple

try:
    import torch  # type: ignore
    _HAS_TORCH = True
except Exception:
    torch = None  # type: ignore
    _HAS_TORCH = False

_HAS_TRANSFORMERS = False
try:
    from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
    _HAS_TRANSFORMERS = True
except Exception:
    _HAS_TRANSFORMERS = False

# Cache key: f"{model_id}@{device}"
_LLM_CACHE: Dict[str, Tuple["AutoTokenizer", "AutoModelForCausalLM", str]] = {}


def _select_device(env_key: str = "LLM_DEVICE") -> str:
    """
    Select device for local LLM generation.
    Priority:
      1) Explicit override via env LLM_DEVICE in {mps,cuda,cpu}
      2) Auto-detect: MPS -> CUDA -> CPU
    Also enables PYTORCH_ENABLE_MPS_FALLBACK=1 for Metal stability.
    """
    dev = (os.getenv(env_key) or "").strip().lower()
    if dev in {"mps", "cuda", "cpu"}:
        if dev == "mps":
            os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        return dev
    if _HAS_TORCH:
        try:
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
                return "mps"
        except Exception:
            pass
        try:
            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
    return "cpu"


def _device_banner(kind: str, model_name: str) -> None:
    try:
        print(f"[llm] device={kind} model={model_name}", file=sys.stderr)
    except Exception:
        pass


def _get_local_llm(model_id: str) -> Optional[Tuple["AutoTokenizer", "AutoModelForCausalLM", str]]:
    """
    Load and cache a small local LLM (≥1B params) for quick summarization.
    Default suggested: TinyLlama/TinyLlama-1.1B-Chat-v1.0
    """
    if not (_HAS_TORCH and _HAS_TRANSFORMERS):
        return None

    device = _select_device("LLM_DEVICE")
    cache_key = f"{model_id}@{device}"
    if cache_key in _LLM_CACHE:
        return _LLM_CACHE[cache_key]

    try:
        tok = AutoTokenizer.from_pretrained(model_id, use_fast=True)
        # dtype: use float16 on mps/cuda; cpu stays float32 for compatibility
        if device == "cuda":
            dtype = torch.float16
        elif device == "mps":
            # MPS generally prefers float16 for speed and memory
            dtype = torch.float16
        else:
            dtype = torch.float32

        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype=dtype,
            low_cpu_mem_usage=True,
            trust_remote_code=True,
        )
        try:
            if device in {"cuda", "mps"}:
                model.to(device)
        except Exception:
            # Fall back to CPU if move fails
            device = "cpu"
            try:
                model.to(device)
            except Exception:
                pass

        _LLM_CACHE[cache_key] = (tok, model, device)
        _device_banner(device, model_id)
        return _LLM_CACHE[cache_key]
    except Exception as e:
        print(f"[llm] load error for {model_id}: {e}", file=sys.stderr)
        return None


def fallback_theme_summary(theme_text: str, max_len: int = 120) -> str:
    """
    Deterministic, zero-LLM fallback summary.
    """
    t = (theme_text or "").strip().replace("\n", " ")
    if len(t) > max_len:
        t = t[: max_len - 1] + "…"
    return f"Theme: {t}" if t else ""


def generate_theme_summary(
    theme_text: str,
    model_id: Optional[str] = None,
    max_new_tokens: int = 48,
) -> str:
    """
    Generate a concise theme summary using a small local LLM. Returns empty string on failure.
    Uses environment variables when arguments are None:
      - LLM_MODEL (default: TinyLlama/TinyLlama-1.1B-Chat-v1.0)
      - LLM_MAX_NEW_TOKENS
    """
    if not theme_text:
        return ""
    model_id = model_id or os.getenv("LLM_MODEL", "TinyLlama/TinyLlama-1.1B-Chat-v1.0")
    try:
        max_new_tokens = int(os.getenv("LLM_MAX_NEW_TOKENS", str(max_new_tokens)))
    except Exception:
        pass

    handle = _get_local_llm(model_id)
    if not handle:
        return fallback_theme_summary(theme_text)

    tok, model, device = handle

    # Simple concise instruction; keep deterministic and short
    prompt = (
        "Summarize this subreddit theme in at most 16 words. "
        "Prefer nouns and key phrases. No trailing punctuation.\n"
        f"Theme context: {theme_text}\n"
        "Summary:"
    )

    try:
        # Try chat template if available
        input_text = prompt
        if hasattr(tok, "apply_chat_template"):
            try:
                messages = [
                    {"role": "system", "content": "You are a concise assistant."},
                    {"role": "user", "content": prompt},
                ]
                input_text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            except Exception:
                input_text = prompt

        inputs = tok(input_text, return_tensors="pt")
        if device in {"cuda", "mps"}:
            inputs = {k: v.to(device) for k, v in inputs.items()}
        gen_cfg = dict(
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=0.0,
            top_p=1.0,
            pad_token_id=getattr(tok, "pad_token_id", getattr(tok, "eos_token_id", None)),
            eos_token_id=getattr(tok, "eos_token_id", None),
        )
        with torch.inference_mode():
            out = model.generate(**inputs, **gen_cfg)
        text = tok.decode(out[0], skip_special_tokens=True)
        # Heuristic: take last line after 'Summary:' if present
        if "Summary:" in text:
            text = text.split("Summary:", 1)[-1]
        text = text.strip()
        # Keep to a single line, no trailing punctuation
        text = text.replace("\n", " ").strip()
        if text.endswith((".", "!", "?")):
            text = text[:-1]
        # Clip very long responses defensively
        if len(text) > 200:
            text = text[:199] + "…"
        return text or fallback_theme_summary(theme_text)
    except Exception as e:
        print(f"[llm] generate error: {e}", file=sys.stderr)
        return fallback_theme_summary(theme_text)