#!/usr/bin/env python3
"""Cache small quest DBC lookup tables from the existing world container, read only."""
import json
from pathlib import Path
import struct
import subprocess
import os
from deployment_config import container
from connection import env


def read_dbc(name):
    data = subprocess.run(['docker', 'exec', container('world_container'), 'cat',
        env('DBC_PATH', '/azerothcore/env/dist/data/dbc').rstrip('/') + '/' + name + '.dbc'], capture_output=True, check=True, timeout=20).stdout
    magic, count, fields, size, strings = struct.unpack_from('<4s4I', data)
    if magic != b'WDBC' or size != fields*4 or len(data) != 20+count*size+strings or count > 100000:
        raise ValueError('Unexpected DBC layout')
    block = data[20+count*size:]
    def text(offset):
        end = block.find(b'\0', offset)
        if offset >= len(block) or end < 0: raise ValueError('Invalid DBC text')
        return block[offset:end].decode('utf-8')
    return list(struct.iter_unpack('<'+'I'*fields, data[20:20+count*size])), text


if __name__ == '__main__':
    output = {}
    for key, name, field in [('areas','AreaTable',11), ('sorts','QuestSort',1), ('factions','Faction',23), ('spells','Spell',136)]:
        rows, text = read_dbc(name)
        output[key] = {str(row[0]):text(row[field]) for row in rows if text(row[field])}
    rows, _ = read_dbc('QuestXP')
    output['xp'] = {str(row[0]):list(row[1:11]) for row in rows}
    rows, _ = read_dbc('QuestFactionReward')
    output['reputation'] = {str(row[0]):[v if v < 2147483648 else v-4294967296 for v in row[1:11]] for row in rows}
    rows, _ = read_dbc('WorldMapArea')
    output['world_areas'] = {str(row[0]):{'map':row[1], 'area':row[2]} for row in rows}
    path = Path(__file__).resolve().parent/'assets'/'quest-metadata.json'
    path.write_text(json.dumps(output,ensure_ascii=False))
    print('Cached quest area, category, faction, spell and base XP lookups in assets/quest-metadata.json.')
