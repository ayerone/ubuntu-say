"""Settings for ubuntu-say, read from config.toml next to this file.

Copy config.example.toml to config.toml and edit. Every key is optional; the
defaults below apply to anything left out. config.toml is read when the daemon
starts, so kill the daemon after editing it.
"""
import os
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.toml")

DEFAULTS = {
    "model": "kokoro-v1.0.onnx",    # Kokoro ONNX model file (relative to this project, or absolute)
    "voices": "voices-v1.0.bin",    # voices file that matches the model
}


def load_config():
    config = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "rb") as f:
            user = tomllib.load(f)
        unknown = set(user) - set(DEFAULTS)
        if unknown:
            raise SystemExit(f"{CONFIG_PATH}: unknown setting(s): {', '.join(sorted(unknown))}")
        config.update(user)
    return config
