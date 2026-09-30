"""Configuration loading and saving (~/.config/dzdk/config.yaml)."""
import os
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_API_URL = "https://services.dzaleka.com/api"

DEFAULT_CONFIG: Dict[str, Any] = {
    "api_url": DEFAULT_API_URL,
    "timeout": 30,
    # Seconds a cached API response stays fresh. 0 disables the disk cache.
    "cache_ttl": 300,
    # Serve stale cached data when the network is unreachable.
    "offline_fallback": True,
    # Textual theme used by `dzdk tui`.
    "theme": "dzaleka",
    # Size `dzdk tui` asks the terminal window to grow to when it is smaller,
    # as "COLUMNSxROWS", or "off" to never resize the window.
    "window_size": "140x42",
    # Width of the list pane beside the details, in percent.
    "sidebar_width": 46,
}


def config_dir() -> Path:
    return Path(os.environ.get("DZDK_CONFIG_DIR", str(Path.home() / ".config" / "dzdk")))


def config_file() -> Path:
    return config_dir() / "config.yaml"


def cache_dir() -> Path:
    return config_dir() / "cache"


def normalize_api_url(url: str) -> str:
    """Ensure the URL has a scheme and ends with /api."""
    url = url.strip()
    if not url.startswith("http"):
        url = f"https://{url}"
    url = url.rstrip("/")
    if not url.endswith("/api"):
        url += "/api"
    return url


def load_config() -> Dict[str, Any]:
    """Load configuration, falling back to defaults for missing keys.

    Raises yaml.YAMLError if the file exists but is not valid YAML.
    """
    config = dict(DEFAULT_CONFIG)
    path = config_file()
    if path.exists():
        with open(path) as f:
            loaded = yaml.safe_load(f) or {}
        if not isinstance(loaded, dict):
            raise yaml.YAMLError(f"{path} must contain a mapping")
        config.update(loaded)
    config["api_url"] = normalize_api_url(str(config["api_url"]))
    return config


def save_config(config: Dict[str, Any]) -> None:
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
