"""Private Hub connection settings; never reads or changes game-server configuration."""
import json
import os
from pathlib import Path
import re
import tempfile

CONFIG = Path(__file__).resolve().parent / 'connection.json'
KEYS = {'db_mode', 'db_host', 'db_port', 'db_user', 'db_password', 'db_container',
        'world_container', 'dbc_path', 'characters_schema', 'world_schema', 'auth_schema',
        'realm_id', 'host_name', 'dbc_source'}


def validate(config):
    if not isinstance(config, dict) or set(config) - KEYS:
        raise ValueError('connection.json contains unsupported settings; use examples/connection.json.')
    result = dict(config)
    for key, value in result.items():
        if key in ('db_port', 'realm_id') and type(value) is int:
            result[key] = value = str(value)
        if not isinstance(value, str) or '\0' in value:
            raise ValueError('Connection settings must be text (ports and realm IDs may also be integers).')
    if result.get('db_mode') not in ('docker', 'direct'):
        raise ValueError('Set db_mode to docker or direct in connection.json.')
    if 'dbc_source' in result and result['dbc_source'] not in ('local', 'docker'):
        raise ValueError('Set dbc_source to local or docker.')
    for key in ('characters_schema', 'world_schema', 'auth_schema'):
        if key in result and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', result[key]):
            raise ValueError('Database names must be SQL identifiers.')
    for key in ('db_container', 'world_container'):
        if key in result and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', result[key]):
            raise ValueError('Use Docker container names or IDs for deployment targets.')
    port = result.get('db_port', '3306')
    if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError('Choose a valid database port.')
    if 'realm_id' in result and (not result['realm_id'].isascii() or not result['realm_id'].isdigit() or int(result['realm_id']) < 1):
        raise ValueError('Choose a positive realm ID.')
    for key in ('db_host', 'db_user', 'dbc_path'):
        if key in result and not result[key].strip():
            raise ValueError('Host, user and DBC directory settings cannot be blank.')
    return result


def load(path=None):
    path = Path(path) if path is not None else CONFIG
    if not path.exists():
        return {}
    try:
        config = json.loads(path.read_text())
    except (OSError, ValueError):
        raise ValueError('Cannot read connection.json; check its permissions and JSON syntax.') from None
    return validate(config)


def save(config, path=None):
    """Write an owner-only file atomically, without replacing an existing realm's settings."""
    path = Path(path) if path is not None else CONFIG
    config = validate(config)
    if path.exists():
        if load(path) != config:
            raise ValueError('Existing connection settings differ. Use a fresh installation for another realm.')
        path.chmod(0o600)
        return
    fd, temporary = tempfile.mkstemp(prefix='.connection-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(config, out, indent=2)
            out.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def environment(name, default=None):
    """Journey Hub names win; earlier installations keep their environment settings."""
    for prefix in ('JOURNEY_HUB_', 'CHARACTER_HUB_', 'LEMMINGS_'):
        key = prefix + name
        if key in os.environ:
            return os.environ[key]
    return load().get(name.lower(), default)
