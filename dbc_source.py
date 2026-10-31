"""Read extracted server DBCs from a local directory or an existing world container."""
from pathlib import Path
import re
import subprocess
from connection import env
from deployment_config import container


def read_dbc_bytes(name):
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
    path = env('DBC_PATH', '/azerothcore/env/dist/data/dbc').rstrip('/') + '/' + name + '.dbc'
    return subprocess.run(['docker', 'exec', container('world_container'), 'cat', path],
                          capture_output=True, check=True, timeout=20).stdout
