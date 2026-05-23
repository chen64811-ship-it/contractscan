# -*- coding: utf-8 -*-
"""
Configuration Management Service
Manages LLM API configuration (API Key, Base URL, Model).
Configuration persisted to backend/llm_config.json.
"""
import os
import json
from dotenv import load_dotenv

# Load .env file (backend/.env)
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

CONFIG_PATH = os.path.join(BACKEND_DIR, "llm_config.json")


def get_config():
    """
    Read configuration, return dict.
    Priority: .env file > llm_config.json > defaults
    """
    # Prefer .env
    env_api_key = os.getenv("LLM_API_KEY", "").strip()
    env_api_base = os.getenv("LLM_API_BASE", "").strip()
    env_model = os.getenv("LLM_MODEL", "").strip()

    default_config = {
        "api_key": "",
        "api_base": "https://api.minimax.chat/v1",
        "model": "MiniMax-M2.7",
        "temperature": 0.7,
        "max_tokens": 2000,
        "enabled": True  # whether LLM-enhanced Q&A is enabled
    }

    # If .env has config, use it
    if env_api_key:
        default_config["api_key"] = env_api_key
        default_config["api_base"] = env_api_base or "https://api.minimax.chat/v1"
        default_config["model"] = env_model or "MiniMax-M2.7"
        default_config["enabled"] = True
        return default_config

    # Otherwise read llm_config.json
    if not os.path.exists(CONFIG_PATH):
        return default_config

    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)
        # Merge defaults to ensure new fields exist
        for k, v in default_config.items():
            if k not in config:
                config[k] = v
        return config
    except Exception:
        return default_config


def save_config(config):
    """Save configuration to file."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[Config save failed] {e}")
        return False


def is_llm_enabled():
    """Check if a valid LLM is configured."""
    cfg = get_config()
    return bool(cfg.get("api_key", "").strip()) and cfg.get("enabled", False)
