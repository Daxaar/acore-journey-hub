"""Local storage and parsing for original Wrath combat logs."""
from contextlib import closing
import csv
from datetime import datetime
from pathlib import Path
import re
import sqlite3

MAX_LOG = 4 * 1024 * 1024
MAX_REQUEST = MAX_LOG * 2
STAMP = re.compile(r'^(\d{1,2}/\d{1,2} \d{2}:\d{2}:\d{2}\.\d{1,3})\s{2,}(.*)$')
SWINGS = {'SWING_DAMAGE', 'SWING_MISSED'}
EVENTS = {
    'SWING_DAMAGE', 'RANGE_DAMAGE', 'SPELL_DAMAGE', 'SPELL_PERIODIC_DAMAGE',
    'SPELL_HEAL', 'SPELL_PERIODIC_HEAL', 'SPELL_CAST_START', 'SPELL_CAST_SUCCESS',
    'SPELL_INTERRUPT', 'SPELL_AURA_APPLIED', 'SPELL_AURA_REMOVED',
    'SWING_MISSED', 'SPELL_MISSED', 'RANGE_MISSED', 'SPELL_PERIODIC_MISSED',
    'UNIT_DIED', 'UNIT_DESTROYED', 'SPELL_RESURRECT', 'SPELL_DISPEL', 'SPELL_STOLEN',
    'SPELL_AURA_BROKEN', 'SPELL_AURA_BROKEN_SPELL', 'SPELL_AURA_REFRESH',
    'SPELL_ENERGIZE', 'SPELL_PERIODIC_ENERGIZE', 'DAMAGE_SHIELD', 'DAMAGE_SPLIT',
    'DAMAGE_SHIELD_MISSED', 'ENVIRONMENTAL_DAMAGE',
}


def parse_log(text):
    events = []
    first = previous = None
    year = 2000
    for line in text.splitlines():
        match = STAMP.match(line.lstrip('\ufeff'))
        if not match:
            continue
        try:
            row = next(csv.reader([match[2]]))
            kind = row[0]
            if kind not in EVENTS:
                continue
            moment = datetime.strptime(f'{year}/{match[1]}', '%Y/%m/%d %H:%M:%S.%f')
            if previous and (previous - moment).days > 300:
                year += 1
                moment = moment.replace(year=year)
            source, target = (name if name.lower() != "nil" else "" for name in (row[2], row[5]))
            spell_id = None
            if kind in SWINGS:
                spell = 'Melee'
                offset = 7
            elif kind.startswith('UNIT_'):
                spell = ''
                offset = 7
            elif kind == 'ENVIRONMENTAL_DAMAGE':
                spell = row[7]
                offset = 8
            else:
                spell_id = int(row[7])
                spell = row[8]
                offset = 10
            amount = extra = absorbed = 0
            power = None
            detail = ''
            if kind.endswith(('_DAMAGE', '_HEAL')) or kind in {'DAMAGE_SHIELD', 'DAMAGE_SPLIT'}:
                extra = max(0, int(row[offset + 1]))
                amount = max(0, int(row[offset]) - extra)
                if not kind.endswith('_HEAL'):
                    absorbed = max(0, int(row[offset + 5])) if row[offset + 5] != 'nil' else 0
            elif kind.endswith('_MISSED') and row[offset] == 'ABSORB':
                values = [int(value) for value in row[offset + 1:] if value.isdecimal()]
                absorbed = values[-1] if values else 0
            elif kind.endswith('_ENERGIZE'):
                amount = max(0, int(row[offset]))
                power = int(row[offset + 1])
            elif kind in {'SPELL_DISPEL', 'SPELL_STOLEN', 'SPELL_INTERRUPT', 'SPELL_AURA_BROKEN_SPELL'}:
                detail = row[offset + 1] if len(row) > offset + 1 else ''
            friendly = bool(int(row[3], 16) & int(row[6], 16) & 0x10)
        except (ValueError, IndexError, csv.Error):
            continue
        if first is None:
            first = moment
        previous = moment
        events.append([round((moment - first).total_seconds(), 3), kind, source, target,
                       spell, amount, spell_id, row[1], row[4], extra, absorbed, power, detail, friendly])
    if not events:
        raise ValueError('No supported Wrath combat events found in this file.')
    return events


# Original Wrath Deadmines creature entries.
DEADMINES = {644, 643, 1763, 646, 647, 639, 645, 3586}


def boss_windows(events):
    """Approximate each recorded boss pull from its first hostile event to death."""
    active, windows = {}, []
    for event in events:
        time, kind, source, target, _, _, _, source_id, target_id, *rest = event
        if kind == 'UNIT_DIED' and target_id in active:
            start, name, _ = active.pop(target_id)
            windows.append([start, time, name])
        if not (kind.endswith(('_DAMAGE', '_MISSED')) or kind in {'DAMAGE_SHIELD', 'SPELL_CAST_SUCCESS'}):
            continue
        for guid, name, other in ((source_id, source, target_id), (target_id, target, source_id)):
            if guid == other or not re.fullmatch(r'0xF13[0-9a-f]{13}', guid, re.I):
                continue
            if int(guid[6:12], 16) not in DEADMINES:
                continue
            start = active.get(guid, (time, name, time))[0]
            active[guid] = (start, name, time)
    return sorted(windows + [[start, end, name] for start, name, end in active.values()])


class CombatLogStore:
    def __init__(self, path=None):
        self.path = path or Path(__file__).with_name('combat-logs.sqlite3')

    def connect(self):
        db = sqlite3.connect(self.path)
        db.execute('CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, title TEXT NOT NULL,'
                   ' saved TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, body TEXT NOT NULL)')
        with db:
            db.execute('BEGIN IMMEDIATE')
            if 'dungeon' not in {row[1] for row in db.execute('PRAGMA table_info(logs)')}:
                db.execute('ALTER TABLE logs ADD COLUMN dungeon INTEGER NOT NULL DEFAULT 0')
        return db

    def list(self):
        with closing(self.connect()) as db:
            return db.execute('SELECT id, title, saved FROM logs ORDER BY id DESC').fetchall()

    @staticmethod
    def validate_title(title):
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            raise ValueError('Provide a log name of up to 120 characters.')
        return title.strip()

    def rename(self, log_id, title):
        title = self.validate_title(title)
        with closing(self.connect()) as db, db:
            if not db.execute('UPDATE logs SET title=? WHERE id=?', (title, log_id)).rowcount:
                raise LookupError('Saved log not found.')

    def save(self, title, body, dungeon=False):
        title = self.validate_title(title)
        if not isinstance(body, str) or len(body.encode('utf-8')) > MAX_LOG:
            raise ValueError('Choose a combat log up to 4 MiB.')
        parse_log(body)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM logs').fetchone()[0] >= 25:
                raise ValueError('Delete a saved log before importing another. The limit is 25.')
            return db.execute('INSERT INTO logs (title, body, dungeon) VALUES (?, ?, ?)',
                              (title, body, int(dungeon is True))).lastrowid

    def get(self, log_id):
        with closing(self.connect()) as db:
            row = db.execute('SELECT title, body, dungeon FROM logs WHERE id=?', (log_id,)).fetchone()
        if row is None:
            raise LookupError('Saved log not found.')
        events = parse_log(row[1])
        icons_path = self.path.parent / 'assets/tooltip-metadata.json'
        icons = {}
        if icons_path.is_file():
            import json
            spells = json.loads(icons_path.read_text()).get('spells', {})
            for spell_id in {event[6] for event in events if event[6]}:
                icon = spells.get(str(spell_id), {}).get('icon')
                if icon and re.fullmatch(r'[a-zA-Z0-9_]+', icon):
                    icons[spell_id] = icon
        return {'title': row[0], 'events': events, 'dungeon': bool(row[2]),
                'bosses': boss_windows(events), 'icons': icons}

    def delete(self, log_id):
        with closing(self.connect()) as db, db:
            if not db.execute('DELETE FROM logs WHERE id=?', (log_id,)).rowcount:
                raise LookupError('Saved log not found.')
