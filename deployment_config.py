"""Installation-specific Docker targets; environment overrides saved settings."""
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'deployment.json'
DEFAULTS = {'db_container': 'database',
            'world_container': 'worldserver'}


def validate(config):
    if not isinstance(config, dict) or set(config) != set(DEFAULTS):
        raise ValueError('deployment.json must contain db_container and world_container.')
    if any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value)
           for value in config.values()):
        raise ValueError('Use Docker container names or IDs for deployment targets.')
    return config


def container(kind):
    config = validate(json.loads(CONFIG.read_text())) if CONFIG.exists() else DEFAULTS
    return os.environ.get('CHARACTER_HUB_' + kind.upper(), os.environ.get('LEMMINGS_' + kind.upper(), config[kind.lower()]))
