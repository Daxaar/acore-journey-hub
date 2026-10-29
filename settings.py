"""Atomic dashboard-local settings. No setting changes MySQL globals or server configuration."""

import copy
import json
from pathlib import Path
import threading

THEMES = ('forest', 'frost', 'crimson', 'arcane', 'parchment')
FONTS = ('classic', 'modern', 'bookish', 'monospace')
DEFAULTS = {'sql': {'base_tables_only': True, 'execution_timeout': True, 'row_limit': True},
            'appearance': {'theme': 'forest', 'font': 'classic'}}


def validate_settings(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Settings must contain sql and appearance only.')
    sql = value['sql']
    appearance = value['appearance']
    if not isinstance(sql, dict) or set(sql) != set(DEFAULTS['sql']):
        raise ValueError('Choose the three supported SQL switches.')
    if any(type(flag) is not bool for flag in sql.values()):
        raise ValueError('SQL switches must be true or false.')
    if (not isinstance(appearance, dict) or set(appearance) != {'theme', 'font'}
            or appearance['theme'] not in THEMES or appearance['font'] not in FONTS):
        raise ValueError('Choose a supported theme and font preset.')
    return copy.deepcopy(value)


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None
        self.lock = threading.Lock()
        self.value = copy.deepcopy(DEFAULTS)
        if self.path and self.path.exists():
            self.value = validate_settings(json.loads(self.path.read_text()))

    def get(self):
        with self.lock:
            return copy.deepcopy(self.value)

    def save(self, value):
        value = validate_settings(value)
        with self.lock:
            if self.path:
                temporary = self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps(value, indent=2) + '\n')
                temporary.chmod(0o600)
                temporary.replace(self.path)
            self.value = value
            return copy.deepcopy(value)
