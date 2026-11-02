"""Read extracted server DBCs from a local directory or an existing world container."""
from pathlib import Path
import re
import subprocess
from connection import env
from deployment_config import container


_DOCKER_DBC_DIRECTORIES = ('/data/dbc', '/azerothcore/env/dist/data/dbc')
_docker_dbc_directory = None


def read_dbc_bytes(name):
    global _docker_dbc_directory
    if not re.fullmatch(r'[A-Za-z0-9_]+', name):
        raise ValueError('Choose a valid DBC table name.')
    mode = env('DB_MODE', 'docker')
    source = env('DBC_SOURCE', 'local' if mode == 'direct' else 'docker')
    if source == 'local':
        directory = env('DBC_PATH')
        if not directory:
            raise ValueError('Set dbc_path in connection.json to the server data/dbc directory.')
        path = Path(directory).expanduser() / (name + '.dbc')
        try:
            return path.read_bytes()
        except OSError:
            raise ValueError('Cannot read '+name+'.dbc; check dbc_path and file permissions.') from None
    if source != 'docker':
        raise ValueError('DBC_SOURCE must be local or docker.')
    configured_directory = env('DBC_PATH')
    if configured_directory is not None:
        directories = (configured_directory,)
    else:
        preferred = [_docker_dbc_directory] if _docker_dbc_directory else []
        directories = tuple(dict.fromkeys(preferred + list(_DOCKER_DBC_DIRECTORIES)))
    errors = []
    for directory in directories:
        path = directory.rstrip('/') + '/' + name + '.dbc'
        try:
            data = subprocess.run(['docker', 'exec', container('world_container'), 'cat', path],
                                  capture_output=True, check=True, timeout=20).stdout
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr or b''
            if isinstance(detail, bytes):
                detail = detail.decode('utf-8', 'replace')
            errors.append(f'{path}: {detail.strip() or "docker exec failed"}')
            continue
        _docker_dbc_directory = directory
        return data
    raise ValueError(f'Cannot read {name}.dbc from the world container. Checked '
                     f'{", ".join(directories)}. Set dbc_path in connection.json to the '
                     f'DBC directory inside the container. Details: {"; ".join(errors)}') from None
