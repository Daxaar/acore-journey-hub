#!/usr/bin/env python3
"""Configure a local installation for a running AzerothCore Docker environment."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from deployment_config import CONFIG, ROOT, validate
from groups import Groups, validate_group


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db-container', required=True)
    parser.add_argument('--world-container', required=True)
    parser.add_argument('--members', nargs='+', help='Optional exact roster of 1–10 names')
    parser.add_argument('--group-name', default='Active Party')
    parser.add_argument('--guild-name', help='Optional exact guild membership check')
    parser.add_argument('--skip-assets', action='store_true', help='Install dependencies without generating server metadata')
    args = parser.parse_args()
    config = validate({'db_container': args.db_container, 'world_container': args.world_container})
    if args.members:
        validate_group(args.group_name, args.members)
    if CONFIG.exists() and validate(json.loads(CONFIG.read_text())) != config:
        parser.error('This installation already targets different containers. Extract a fresh package into a separate directory to avoid mixing history and cached assets.')
    # Environment overrides must agree so setup cannot read a different realm.
    import os
    for key, value in config.items():
        for prefix in ('CHARACTER_HUB_', 'LEMMINGS_'):
            env = prefix + key.upper()
            if env in os.environ and os.environ[env] != value:
                parser.error('Unset conflicting ' + env + ' before deployment.')
    if not CONFIG.exists():
        with CONFIG.open('x') as out:
            out.write(json.dumps(config, indent=2) + '\n')
        CONFIG.chmod(0o600)
    subprocess.run(['bash', str(ROOT / 'setup.sh')] + (['--skip-assets'] if args.skip_assets else []), check=True, cwd=ROOT)
    if args.members:
        from prepare_profession_assets import query
        from mysql_access import DatabaseError
        try:
            print(bootstrap(ROOT / 'groups.json', args.members, query, args.group_name, args.guild_name))
        except DatabaseError as exc:
            parser.exit(1, 'Guild discovery failed: ' + str(exc) + '\n')
    print('Deployment ready. Run bash start.sh; open http://localhost:8765.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print('Deployment failed: ' + str(exc), file=sys.stderr)
        sys.exit(1)
