#!/usr/bin/env python3
"""Read existing server DBC metadata into this dashboard only. No server changes."""
import json
import re
import struct
import subprocess
import os
from deployment_config import container
from connection import env
from pathlib import Path


def dbc(filename, field):
    data = subprocess.run(['docker', 'exec', container('world_container'), 'cat',
                           env('DBC_PATH', '/azerothcore/env/dist/data/dbc').rstrip('/') + '/' + filename + '.dbc'],
                          capture_output=True, check=True, timeout=20).stdout
    magic, count, fields, size, strings = struct.unpack_from('<4s4I', data)
    if magic != b'WDBC' or size != fields * 4 or fields <= field or len(data) != 20 + count * size + strings:
        raise ValueError('Unexpected DBC layout')
    block = data[20 + count * size:]
    result = {}
    for row in struct.iter_unpack('<' + 'I' * fields, data[20:20 + count * size]):
        offset = row[field]
        if offset >= strings:
            raise ValueError('Invalid DBC string')
        value = block[offset:block.find(b'\0', offset)].decode('utf-8')
        if value:
            result[str(row[0])] = value
    return result


if __name__ == '__main__':
    icons = {key: value.lower() for key, value in dbc('ItemDisplayInfo', 5).items()
             if re.fullmatch(r'[A-Za-z0-9_]{1,100}', value)}
    result = {'icons': icons, 'properties': dbc('ItemRandomProperties', 7),
              'suffixes': dbc('ItemRandomSuffix', 1), 'enchants': dbc('SpellItemEnchantment', 14)}
    target = Path(__file__).resolve().parent / 'assets' / 'item-metadata.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    print(f'Cached {len(icons)} item display/icon mappings inside the dashboard.')
