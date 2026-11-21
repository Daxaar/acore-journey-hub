"""Prepare local map coordinate bounds from a Wrath client."""
import argparse
import json
import math
import re
from pathlib import Path
import struct

from client_models import Archives, client_path

ROOT = Path(__file__).resolve().parent


def zone_details(client, archives):
    data = archives.read(r'DBFilesClient\AreaTable.dbc')
    magic, count, fields, size, strings = struct.unpack_from('<4s4I', data)
    base = 20 + count * size
    if magic != b'WDBC' or fields < 12 or size != fields * 4 or len(data) != base + strings:
        return {}
    addon = client / 'Interface/AddOns/Leatrix_Maps/Leatrix_Maps.lua'
    ranges = {}
    if addon.is_file():
        for name, low, high in re.findall(
            r'^\s*\["([^"]+)"\]\s*=\s*\{\s*(\d+)\s*,\s*(\d+)',
            addon.read_text(encoding='utf-8-sig'), re.M,
        ):
            if 0 < int(low) <= int(high) <= 80:
                ranges[name] = [int(low), int(high)]
    details = {}
    for offset in range(20, base, size):
        zone = struct.unpack_from('<I', data, offset)[0]
        name_offset = struct.unpack_from('<I', data, offset + 44)[0]
        if 0 < name_offset < strings:
            start = base + name_offset
            name = data[start:data.index(b'\0', start)].decode('utf-8', errors='replace')
            details[zone] = {'name': name}
            if name in ranges:
                details[zone]['levels'] = ranges[name]
    return details


def prepare(client, output):
    client = client_path(str(client))
    archives = Archives(client)
    try:
        data = archives.read(r'DBFilesClient\WorldMapArea.dbc')
        details = zone_details(client, archives)
    finally:
        archives.close()
    magic, count, fields, size, strings = struct.unpack_from('<4s4I', data)
    if (magic, fields, size) != (b'WDBC', 11, 44) or len(data) != 20 + count * size + strings:
        raise ValueError('Expected Wrath WorldMapArea.dbc')
    maps, zones = {}, {}
    for index in range(count):
        _, map_id, zone_id, _, y1, y2, x1, x2, virtual_map, floor, _ = struct.unpack_from(
            '<3iI4f3i', data, 20 + index * size)
        if floor > 0 or x1 == x2 or y1 == y2 or not all(map(math.isfinite, (x1, x2, y1, y2))):
            continue
        bounds = [x1, x2, y1, y2]
        if zone_id == 0:
            maps[str(map_id)] = bounds
        else:
            zones[f'{map_id}:{zone_id}'] = {'bounds': bounds, 'continent': map_id if virtual_map < 0 else virtual_map, **details.get(zone_id, {})}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps({'maps': maps, 'zones': zones}), encoding='utf-8')
    temporary.replace(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client')
    parser.add_argument('--output', type=Path, default=ROOT / 'assets/live-world-maps.json')
    args = parser.parse_args()
    prepare(args.client, args.output)
