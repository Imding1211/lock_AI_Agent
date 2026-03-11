import os
import tomllib
from dotenv import load_dotenv

load_dotenv()

def load_config(file_path="config.toml"):
    with open(file_path, "rb") as f:
        data = tomllib.load(f)
        return (
            data.get("databases", []),
            data.get("llm", {"provider": "ollama"}),
            data.get("intents", []),
            data.get("memory", {"type": "memory"}),
            data.get("required_slots", {}),
            data.get("system", {"domain": "電子鎖"}),
            data.get("line_bot", {"loading_animation_time": 5}),
            data.get("templates", {"push_fallback_prefix": "【系統通知】讓您久等了，以下是您的回覆：\n"}),
            data.get("user_profile", {"enabled": False, "profile_dir": "./data/profiles"}),
            data.get("debounce", {"buffer_wait": 1.5}),
            data.get("agents", [])
        )

DB_CONFIG, LLM_CONFIG, INTENTS_CONFIG, MEMORY_CONFIG, REQUIRED_SLOTS, SYSTEM_CONFIG, LINE_BOT_CONFIG, TEMPLATES_CONFIG, USER_PROFILE_CONFIG, DEBOUNCE_CONFIG, AGENTS_CONFIG = load_config()
