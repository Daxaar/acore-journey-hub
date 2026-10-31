#!/usr/bin/env python3
"""Set up Character Hub for a Docker or native AzerothCore server."""
import argparse
import getpass
import os
import shutil
import json
from pathlib import Path
import subprocess
import sys

from deployment_config import CONFIG, ROOT, validate
from groups import Groups, validate_group
from connection_config import load as load_connection, save as save_connection, validate as validate_connection


def bootstrap(path, members, query, group_name="Active Party", guild_name=None):
    """Create an explicitly requested roster, optionally requiring a guild."""
    group = validate_group(group_name, members)
    groups = Groups(path)
    if groups.data['groups']:
        return 'Existing groups preserved; guild discovery skipped.'
    guild_filter = (' AND g.name=0x' + guild_name.encode().hex()) if guild_name else ''
    names = ','.join('0x' + name.encode().hex() for name in group['members'])
    rows = query("SELECT JSON_OBJECT('name',c.name) FROM acore_characters.characters c "
                 'LEFT JOIN acore_characters.guild_member gm ON gm.guid=c.guid '
                 'LEFT JOIN acore_characters.guild g ON g.guildid=gm.guildid '
                 f'WHERE c.deleteDate IS NULL AND c.name IN ({names}){guild_filter};')
    found = {row['name'].casefold() for row in rows}
    if found != {name.casefold() for name in group['members']}:
        return 'Target guild does not contain the complete requested roster; dashboard left empty.'
    groups.update({'action': 'create', **group})
    return 'Created requested group from verified target characters.'


def prompt(label, default=None, secret=False):
    suffix = f' [{default}]' if default is not None else ''
    value = getpass.getpass(label + ': ') if secret else input(label + suffix + ': ').strip()
    return value if value else (default if default is not None else '')


def interactive_config():
    print('Character Hub setup — connects read-only to your existing AzerothCore server.')
    mode = prompt('Server type: docker or direct (no containers)', 'docker').lower()
    if mode == 'docker':
        return validate_connection({'db_mode': mode,
            'db_container': prompt('Database container', 'database'),
            'world_container': prompt('Worldserver container', 'worldserver')})
    if mode != 'direct':
        raise ValueError('Choose docker or direct.')
    print('Use a SELECT-only MySQL account. DBC directory means the server data/dbc folder.')
    return validate_connection({'db_mode': mode,
        'db_host': prompt('MySQL host', '127.0.0.1'),
        'db_port': prompt('MySQL port', '3306'),
        'db_user': prompt('MySQL user', 'character_hub'),
        'db_password': prompt('MySQL password', secret=True),
        'characters_schema': prompt('Characters database', 'acore_characters'),
        'world_schema': prompt('World database', 'acore_world'),
        'auth_schema': prompt('Auth database', 'acore_auth'),
        'dbc_path': str(Path(prompt('Local DBC directory')).expanduser().resolve())})


def check_environment(config):
    for key, value in config.items():
        for prefix in ('CHARACTER_HUB_', 'LEMMINGS_'):
            variable = prefix + key.upper()
            if variable in os.environ and os.environ[variable] != value:
                raise ValueError('Unset conflicting ' + variable + ' before setup.')


def preflight(config, skip_assets=False):
    program = 'mysql' if config['db_mode'] == 'direct' else 'docker'
    if not shutil.which(program):
        raise ValueError('Install the ' + ('MySQL 8 command-line client' if program == 'mysql' else 'Docker CLI') + ' before setup.')
    source = config.get('dbc_source', 'local' if config['db_mode'] == 'direct' else 'docker')
    if source == 'docker' and not skip_assets and not shutil.which('docker'):
        raise ValueError('Install the Docker CLI for container DBC access, or choose dbc_source local.')
    if source == 'local' and not skip_assets:
        directory = config.get('dbc_path')
        if not directory or not Path(directory).expanduser().is_dir():
            raise ValueError('Set dbc_path to the readable local server data/dbc directory.')
        for name in ('Spell', 'ItemDisplayInfo'):
            if not (Path(directory).expanduser() / (name + '.dbc')).is_file():
                raise ValueError('The DBC directory is missing ' + name + '.dbc.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='Import a Hub connection JSON file; subsequent starts load the saved copy automatically')
    parser.add_argument('--db-container', help='Existing database container (legacy command-line setup)')
    parser.add_argument('--world-container', help='Existing worldserver container (legacy command-line setup)')
    parser.add_argument('--members', nargs='+', help='Optional exact roster of 1–10 names')
    parser.add_argument('--group-name', default='Active Party')
    parser.add_argument('--guild-name', help='Optional exact guild membership check')
    parser.add_argument('--skip-assets', action='store_true', help='Install dependencies without generating server metadata')
    args = parser.parse_args()
    if args.members:
        validate_group(args.group_name, args.members)
    if args.config and (args.db_container or args.world_container):
        parser.error('Use --config or the container arguments, not both.')
    legacy = bool(args.db_container or args.world_container)
    if legacy:
        if not args.db_container or not args.world_container:
            parser.error('Provide both --db-container and --world-container.')
        targets = validate({'db_container': args.db_container, 'world_container': args.world_container})
        config = {'db_mode': 'docker', **targets}
    elif args.config:
        if not args.config.is_file():
            parser.error('The Hub connection JSON file does not exist.')
        config = load_connection(args.config)
    else:
        config = load_connection()
        if not config and CONFIG.exists():
            config = {'db_mode': 'docker', **validate(json.loads(CONFIG.read_text()))}
            legacy = True
        if not config:
            if not sys.stdin.isatty():
                parser.error('Run setup in a terminal, or supply --config examples/connection.json after editing a private copy.')
            config = interactive_config()
    check_environment(config)
    if CONFIG.exists():
        saved = validate(json.loads(CONFIG.read_text()))
        if config['db_mode'] != 'docker' or any(config.get(key, saved[key]) != value for key, value in saved.items()):
            parser.error('This installation already targets another server. Use a fresh directory to avoid mixing local history.')
    existing = load_connection()
    if existing and existing != validate_connection(config):
        parser.error('Existing connection settings differ. Use a fresh installation for another realm.')
    preflight(config, args.skip_assets)
    if legacy:
        targets = validate({key: config[key] for key in ('db_container', 'world_container')})
        if not CONFIG.exists():
            with CONFIG.open('x') as out:
                out.write(json.dumps(targets, indent=2) + '\n')
            CONFIG.chmod(0o600)
    else:
        save_connection(config)
    subprocess.run(['bash', str(ROOT / 'setup.sh')] + (['--skip-assets'] if args.skip_assets else []), check=True, cwd=ROOT)
    if args.members:
        from prepare_profession_assets import query
        from mysql_access import DatabaseError
        try:
            print(bootstrap(ROOT / 'groups.json', args.members, query, args.group_name, args.guild_name))
        except DatabaseError:
            parser.exit(1, 'Cannot verify the requested roster. Check the connection; existing groups are preserved.\n')
    print('Setup ready. Run bash start.sh; open http://localhost:8765.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, EOFError) as exc:
        print('Deployment failed: ' + str(exc), file=sys.stderr)
        sys.exit(1)
