"""Portable MySQL CLI transport. Credentials remain in the process environment."""
import os
import re
from deployment_config import container


def env(name, default=None):
    return os.environ.get('CHARACTER_HUB_' + name, os.environ.get('LEMMINGS_' + name, default))


def schema(name):
    value = env(name.upper() + '_SCHEMA', 'acore_' + name)
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', value):
        raise ValueError('Database names must be SQL identifiers.')
    return value


def database_sql(sql):
    mapping = { 'acore_' + name: schema(name) for name in ('characters', 'world', 'auth') }
    return re.sub(r'\bacore_(?:characters|world|auth)\b', lambda m: mapping[m[0]], sql)


def database_environment():
    result = os.environ.copy()
    if env('DB_PASSWORD') is not None:
        result['MYSQL_PWD'] = env('DB_PASSWORD')
    return result


def mysql_command(xml=False):
    options = ['--default-character-set=utf8mb4', '--batch', '--connect-timeout=3']
    options += ['--binary-mode', '--xml'] if xml else ['--raw', '--skip-column-names']
    if env('DB_MODE', 'docker') == 'direct':
        port = env('DB_PORT', '3306')
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError('Choose a valid database port.')
        return ['mysql', '--protocol=TCP', '--host=' + env('DB_HOST', '127.0.0.1'),
                '--port=' + port, '--user=' + env('DB_USER', 'character_hub')] + options
    if env('DB_MODE', 'docker') != 'docker':
        raise ValueError('DB_MODE must be docker or direct.')
    # Retains compatibility with existing installations; direct mode supports SELECT-only accounts.
    import shlex
    return ['docker', 'exec', '-i', container('db_container'), 'sh', '-c',
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --user=root ' + shlex.join(options)]
