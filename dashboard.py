#!/usr/bin/env python3
"""Local, read-only quest dashboard. Python standard library; no database/network setup changes."""

import argparse
import sys
import ipaddress
import sqlite3
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
import secrets
import hmac
import os


ROOT = Path(__file__).resolve().parent
CLASSES = {1: 'Warrior', 2: 'Paladin', 3: 'Hunter', 4: 'Rogue', 5: 'Priest', 6: 'Death Knight',
           7: 'Shaman', 8: 'Mage', 9: 'Warlock', 11: 'Druid'}
RACES = {1: 'Human', 2: 'Orc', 3: 'Dwarf', 4: 'Night Elf', 5: 'Undead', 6: 'Tauren', 7: 'Gnome',
         8: 'Troll', 10: 'Blood Elf', 11: 'Draenei'}
STATUSES = {1: 'ready', 3: 'active', 5: 'failed'}


from rested_xp import rested_view
from server_identity import ServerIdentity
from mysql_access import DatabaseError, name_filter, snapshot_sql, read_database
from data_sources import MySQLSource, HttpQuestSource, SourceError
from sql_console import SqlConsole, QueryError
from settings import SettingsStore
from armory import ArmoryProvider
from gear_planner import GearPlanner,PlannerPreferences
from auctions import AuctionProvider
from hub_runtime import registered
from watch_notes import WatchNotes, MAX_NOTE_REQUEST, KEEP_IMAGE
from professions import SkillsProvider
from item_tooltips import ItemTooltipProvider
from training import TrainingProvider
from quest_log import QuestLogProvider
from journal import JournalStore, JournalConflict, MAX_REQUEST
from observed_changes import ObservedChanges
from activity_history import ActivityHistory, EVENT_KINDS
from planning import LocationProvider, enrich_view, load_metadata
from client_models import ClientModels, APPEARANCE


def objectives(row):
    """Describe saved counters, without inventing completion for scripted or reputation requirements."""
    result = []

    def add(key, kind, label, required, current=None, note=None):
        result.append({'key': key, 'kind': kind, 'label': label, 'required': required,
                       'current': current, 'note': note})

    for i in range(1, 5):
        target, count = row.get(f'target{i}') or 0, row.get(f'target_count{i}') or 0
        if target and count:
            kind = 'interact' if target < 0 or (row.get('special_flags') or 0) & 32 else 'kill'
            label = row.get(f'objective_text{i}') or row.get(f'target_name{i}') or f'Target #{abs(target)}'
            add(f'target{i}', kind, label, count, row.get(f'mob{i}', 0))
    for i in range(1, 7):
        item, count = row.get(f'item_id{i}') or 0, row.get(f'item_count{i}') or 0
        if item and count:
            add(f'item{i}', 'item', row.get(f'item_name{i}') or f'Item #{item}', count, row.get(f'item{i}', 0))
    if (row.get('special_flags') or 0) & 2 or row.get('has_area_trigger'):
        add('exploration', 'exploration', row.get('area') or 'Exploration / scripted event', 1,
            int(bool(row.get('explored'))))
    if row.get('player_kills'):
        add('player_kills', 'pvp', 'Opposing players defeated', row['player_kills'], row.get('playercount', 0))
    if row.get('money_required'):
        add('money', 'money', 'Money required (copper)', row['money_required'], row.get('money', 0))
    if row.get('faction') and row.get('reputation_required'):
        add('reputation', 'reputation', f"Reputation with faction #{row['faction']}", row['reputation_required'],
            note='Reputation is not evaluated here; saved quest status determines readiness.')
    if row.get('time_allowed'):
        add('timer', 'timer', 'Timed quest', 1, note='Timer is not a last-save timestamp; see saved quest status.')
    if not result:
        add('script', 'event', 'Delivery, conversation or scripted completion', 1,
            note='No numeric objective is recorded; see saved quest status.')
    return result


def build_view(rows, names):
    found = {r['name'].casefold(): r for r in rows if r['kind'] == 'character'}
    characters = []
    for name in names:
        c = found.get(name.casefold())
        if not c:
            characters.append({'name': name, 'found': False, 'active': 0, 'ready': 0, 'behind': 0})
            continue
        characters.append({'name': c['name'], 'guid': c['guid'], 'found': True,
                           'level': c['level'], 'xp': c['xp'], 'online': bool(c['online']),
                           'rested': rested_view(c),
                           'class_id': c['class'], 'class_name': CLASSES.get(c['class'], 'Unknown'),
                           'race': RACES.get(c['race'], 'Unknown'), 'zone_id': c['zone'],
                           'quest_state_available': c.get('quest_state_available', True),
                           'active': 0, 'ready': 0, 'behind': 0})
    guids = {c['guid'] for c in characters if c['found']}
    grouped = {}
    rewarded = {(r['guid'], r['quest']) for r in rows if r['kind'] == 'rewarded' and r.get('active',1)}
    for row in rows:
        if row['kind'] != 'quest' or row['guid'] not in guids:
            continue
        definition = objectives(row)
        q = grouped.setdefault(row['id'], {
            'id': row['id'], 'title': row.get('title') or f"Quest #{row['id']}",
            'level': row.get('level'), 'description': row.get('description') or '',
            'template_found': bool(row.get('template_found')), 'objectives': [
                {k: obj[k] for k in ['key', 'kind', 'label', 'required', 'note']} for obj in definition],
            'by_guid': {}})
        q['by_guid'][row['guid']] = {
            'status': STATUSES[row['status']], 'counts': {obj['key']: obj['current'] for obj in definition},
            'behind': False, 'behind_objectives': []}
    quests = []
    for q in grouped.values():
        active = q.pop('by_guid')
        q['participants'] = len(active)
        q['shared'] = len(active) >= 2
        q['ready_count'] = sum(p['status'] == 'ready' for p in active.values())
        for obj in q['objectives']:
            # Cap comparison at the required count, so surplus items/money do not mark anyone behind.
            values = [min(p['counts'][obj['key']], obj['required']) for p in active.values()
                      if p['counts'][obj['key']] is not None and p['status'] != 'failed']
            leader = max(values, default=0)
            for p in active.values():
                current = p['counts'][obj['key']]
                if q['shared'] and p['status'] == 'active' and current is not None and current < leader:
                    p['behind_objectives'].append(obj['key'])
        q['progress'] = []
        for c in characters:
            p = active.get(c.get('guid'))
            if p:
                p['behind'] = bool(p['behind_objectives']) or (
                    q['shared'] and q['ready_count'] > 0 and p['status'] == 'active')
                c['active'] += 1
                c['ready'] += int(p['status'] == 'ready')
                c['behind'] += int(p['behind'])
            else:
                status = 'rewarded' if (c.get('guid'), q['id']) in rewarded else 'missing'
                if c.get('found') and not c.get('quest_state_available', True):
                    status = 'unavailable'
                p = {'status': status, 'counts': {}, 'behind': False, 'behind_objectives': []}
            q['progress'].append(p)
        q['attention'] = any(p['behind'] for p in q['progress'])
        quests.append(q)
    quests.sort(key=lambda q: (not q['attention'], not q['shared'], q['title'].casefold()))
    return {'characters': characters, 'quests': quests,
            'summary': {'characters': len(guids), 'active': sum(c['active'] for c in characters),
                        'shared': sum(q['shared'] for q in quests),
                        'ready': sum(c['ready'] for c in characters),
                        'behind': sum(c['behind'] for c in characters)}}


from groups import Groups


class SnapshotCache:
    """Share one bounded database read across tabs; keep the last successful snapshot on failure."""

    def __init__(self, bots=(), reader=read_database, source=None, watch_file=None, groups_file=None, history_file=None, locations=None, notes_file=None):
        self.bots = tuple(bots)
        self.groups = Groups(groups_file)
        self.notes = WatchNotes(notes_file)
        self.source = source or MySQLSource(reader)
        self.history = ActivityHistory(history_file)
        self.locations = locations
        self.planning_metadata = load_metadata()
        self.watch_file = watch_file
        self.lock = threading.Lock()
        self.data = None
        self.error = None
        self.attempted = float('-inf')
        self.changes = ObservedChanges()

    def update_bots(self, names):
        if not isinstance(names, list) or len(names) > 32:
            raise ValueError('Choose up to 32 character names.')
        normalized = []
        for name in names:
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z]{2,12}', name.strip()):
                raise ValueError('Each name must contain 2–12 letters.')
            name = name.strip().capitalize()
            if name not in normalized:
                normalized.append(name)
        with self.lock:
            if self.watch_file:
                temporary = self.watch_file.with_suffix('.tmp')
                temporary.write_text(json.dumps(normalized) + '\n')
                temporary.chmod(0o600)
                temporary.replace(self.watch_file)
            self.changes = ObservedChanges()
            self.bots = tuple(normalized)
            self.data = None
            self.error = None
            self.attempted = float('-inf')
        return normalized

    def update_groups(self, payload):
        with self.lock:
            result = self.groups.update(payload)
            self.changes = ObservedChanges()
            self.data = None
            self.error = None
            self.attempted = float('-inf')
            return result

    def activity(self, view='party', character='', kind='', offset=0):
        if view not in ('party','bots') or kind not in ('',*EVENT_KINDS) or not 0<=offset<=5000:
            raise ValueError('Choose a valid activity filter or page.')
        with self.lock:
            if not self.data:return {'events':[],'total':0,'warning':'Refresh the quest snapshot to establish this group.'}
            chars=self.data['views'][view]['characters']
            if character:
                name_filter('c',[character]);chars=[c for c in chars if c['name'].lower()==character.lower()]
                if not chars:raise ValueError('Choose a character in the displayed group.')
            return self.history.get([c['guid'] for c in chars if c.get('found')],self.data['source']['id'],offset=offset,kind=kind)

    def get(self):
        with self.lock:
            if time.monotonic() - self.attempted >= 2:
                self.attempted = time.monotonic()
                try:
                    group = self.groups.selected()
                    members = group['members'] if group else []
                    names = tuple(dict.fromkeys((*members, *self.bots)))
                    observation = self.source.fetch(names)
                    self.data = {'last_success': datetime.now(timezone.utc).isoformat(),
                                 'observed_at': observation.observed_at, 'source': observation.source,
                                 'save_interval_seconds': observation.source['save_interval_seconds'],
                                 'save_timestamp_available': False,
                                 'groups': self.groups.data,
                                 'views': {'party': build_view(observation.rows, members),
                                           'bots': build_view(observation.rows, self.bots)}}
                    self.data['changes'] = {key: self.changes.observe(key, value, self.data['last_success'])
                                            for key, value in self.data['views'].items()}
                    ids = [q['id'] for view in self.data['views'].values() for q in view['quests']]
                    geo = self.locations.get(ids) if self.locations and ids else {'locations':{},'warning':None}
                    self.history.observe(observation.rows, observation.source['id'], self.data['last_success'])
                    for view in self.data['views'].values():
                        enrich_view(view, observation.rows, geo, self.planning_metadata)
                        view['activity'] = self.history.get([c['guid'] for c in view['characters'] if c.get('found')], observation.source['id'])
                    self.error = None
                except DatabaseError as exc:
                    self.error = str(exc)
            return {'ok': self.error is None, 'error': self.error, 'snapshot': self.data}


ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8'),
          '/emblem.svg': ('emblem.svg', 'image/svg+xml'),
          '/wrath-citadel.svg': ('wrath-citadel.svg', 'image/svg+xml'),
          '/sql': ('sql.html', 'text/html; charset=utf-8'),
          '/sql.js': ('sql.js', 'text/javascript; charset=utf-8')}
ASSETS.update({'/settings': ('settings.html', 'text/html; charset=utf-8'),
               '/settings.js': ('settings.js', 'text/javascript; charset=utf-8'),
               '/appearance.js': ('appearance.js', 'text/javascript; charset=utf-8')})

ASSETS.update({
    '/gear-planner': ('gear-planner.html', 'text/html; charset=utf-8'),
    '/gear-planner.js': ('gear-planner.js', 'text/javascript; charset=utf-8'),
    '/gear-planner.css': ('gear-planner.css', 'text/css; charset=utf-8'),
    '/auctions': ('auctions.html', 'text/html; charset=utf-8'),
    '/auctions.js': ('auctions.js', 'text/javascript; charset=utf-8'),
    '/auction-categories.js': ('auction-categories.js', 'text/javascript; charset=utf-8'),
    '/auctions.css': ('auctions.css', 'text/css; charset=utf-8'),
    '/auction-condensed.ttf': ('auction-condensed.ttf', 'font/ttf'),
    '/journal': ('journal.html', 'text/html; charset=utf-8'),
    '/journal.js': ('journal.js', 'text/javascript; charset=utf-8'),
    '/journal.css': ('journal.css', 'text/css; charset=utf-8'),
    '/training': ('training.html', 'text/html; charset=utf-8'),
    '/training.js': ('training.js', 'text/javascript; charset=utf-8'),
    '/training.css': ('training.css', 'text/css; charset=utf-8'),
    '/professions': ('professions.html', 'text/html; charset=utf-8'),
    '/professions.js': ('professions.js', 'text/javascript; charset=utf-8'),
    '/professions.css': ('professions.css', 'text/css; charset=utf-8'),
    '/skills-ui.js': ('skills-ui.js', 'text/javascript; charset=utf-8'),
    '/quest-log': ('quest-log.html', 'text/html; charset=utf-8'),
    '/quest-log.js': ('quest-log.js', 'text/javascript; charset=utf-8'),
    '/quest-log.css': ('quest-log.css', 'text/css; charset=utf-8'),
    '/quest-horde.svg': ('quest-horde.svg', 'image/svg+xml'),
    '/quest-alliance.svg': ('quest-alliance.svg', 'image/svg+xml'),
    '/inventory': ('inventory.html', 'text/html; charset=utf-8'),
    '/armory': ('armory.html', 'text/html; charset=utf-8'),
    '/client-model.js': ('client-model.js', 'text/javascript; charset=utf-8'),
    '/item-tooltip.js': ('item-tooltip.js', 'text/javascript; charset=utf-8'),
    '/wowhead.js': ('wowhead.js', 'text/javascript; charset=utf-8'),
    '/armory.js': ('armory.js', 'text/javascript; charset=utf-8'),
    '/armory.css': ('armory.css', 'text/css; charset=utf-8'),
    '/paperdoll.svg': ('paperdoll.svg', 'image/svg+xml'),
    '/item-placeholder.svg': ('item-placeholder.svg', 'image/svg+xml')})


def handler(cache, port, console=None, settings=None, allowed_hosts=(), journal=None, planner=None):
    settings = settings or (console.settings if console is not None else SettingsStore())
    console = console or SqlConsole(settings=settings)
    console.settings = settings
    planner = planner or GearPlanner(preferences=PlannerPreferences(ROOT/'gear-planner.json'))
    armory = ArmoryProvider()
    auctions = AuctionProvider()
    skills = SkillsProvider()
    item_tooltips = ItemTooltipProvider()
    training = TrainingProvider()
    quest_log = QuestLogProvider(objectives)
    models = ClientModels()
    journal = journal or JournalStore()
    identity = ServerIdentity()
    token = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        server_version = 'JourneyHub'

        def log_message(self, fmt, *args):
            # Paths/headers are untrusted; keep the local log small and credential-free.
            pass

        def send(self, status, content_type, body):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; "
                             "style-src 'self'; img-src 'self' blob:; connect-src 'self'; "
                             "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # A browser can close a search/refresh request while the read-only query finishes.
                pass

        def allowed(self):
            allowed = {f'localhost:{port}', f'127.0.0.1:{port}', *(f'{h}:{port}' for h in allowed_hosts)}
            # Reject unexpected Host/Origin values to prevent browser access through DNS rebinding.
            if self.headers.get('Host', '') not in allowed:
                self.send(403, 'text/plain', b'Dashboard address not allowed')
                return False
            origin = self.headers.get('Origin')
            if origin and origin not in {f'http://{h}' for h in allowed}:
                self.send(403, 'text/plain', b'Cross-origin access denied')
                return False
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                self.send(403, 'text/plain', b'Cross-site access denied')
                return False
            return True

        def json_response(self, status, payload):
            self.send(status, 'application/json; charset=utf-8', json.dumps(payload).encode('utf-8'))

        def do_POST(self):
            if not self.allowed():
                return
            if not hmac.compare_digest(self.headers.get('X-Dashboard-Token', '').encode(), token.encode()):
                self.json_response(403, {'ok': False, 'error': 'Reload the dashboard before submitting.'})
                return
            try:
                path = urlsplit(self.path).path
                length = int(self.headers.get('Content-Length', '0'))
                limit = MAX_REQUEST if path == '/api/journal' else MAX_NOTE_REQUEST if path == '/api/watch-notes' else 20000
                if not 0 < length <= limit or self.headers.get_content_type() != 'application/json':
                    raise ValueError(f'Send a JSON request no larger than {limit} bytes.')
                self.connection.settimeout(10)
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Expected a JSON object.')
                path = urlsplit(self.path).path
                if path == '/api/journal':
                    if payload.get('action') == 'delete':
                        journal.delete(payload.get('id'),payload.get('revision'))
                        self.json_response(200, {'ok':True})
                    elif payload.get('action','save') == 'save':
                        self.json_response(200, {'ok':True,'entry':journal.save(payload)})
                    else:raise ValueError('Choose save or delete.')
                elif path == '/api/gear-planner/role':
                    if set(payload)!={'guid','role'}:raise ValueError('Provide a character GUID and role.')
                    with cache.lock:group=json.loads(json.dumps(cache.groups.selected()))
                    roles=planner.set_role(group,payload['guid'],payload['role'])
                    self.json_response(200,{'ok':True,'roles':roles})
                elif path == '/api/models/config':
                    self.json_response(200, {'ok': True, 'config': models.save(payload)})
                elif path == '/api/settings':
                    result = settings.save(payload)
                    self.json_response(200, {'ok': True, 'settings': result})
                elif path == '/api/groups':
                    self.json_response(200, {'ok': True, 'groups': cache.update_groups(payload)})
                elif path == '/api/watch-notes':
                    if set(payload)-{'name','text','image'}:raise ValueError('Provide a character note and at most one image.')
                    self.json_response(200, {'ok':True, 'note':cache.notes.save(payload.get('name'),payload.get('text'),payload.get('image',KEEP_IMAGE))})
                elif path == '/api/watchlist':
                    names = cache.update_bots(payload.get('names'))
                    self.json_response(200, {'ok': True, 'names': names})
                elif path == '/api/sql/query':
                    result = console.run(payload.get('query'), payload.get('schema'))
                    self.json_response(200, {'ok': True, 'result': result})
                else:
                    self.json_response(404, {'ok': False, 'error': 'Not found'})
            except JournalConflict as exc:
                self.json_response(409, {'ok':False,'error':str(exc)})
            except LookupError as exc:
                self.json_response(404, {'ok':False,'error':str(exc)})
            except (ValueError, QueryError) as exc:
                self.json_response(400, {'ok': False, 'error': str(exc)})
            except DatabaseError as exc:
                self.json_response(503, {'ok':False,'error':str(exc)})
            except (OSError,sqlite3.Error):
                self.json_response(503, {'ok': False, 'error': 'Local dashboard storage is unavailable.'})

        def do_GET(self):
            if not self.allowed():
                return
            path = urlsplit(self.path).path
            if path.startswith('/watch-note-images/'):
                try:
                    mime,data=cache.notes.image(path.removeprefix('/watch-note-images/'))
                    self.send(200,mime,data)
                except LookupError as exc:self.json_response(404,{'ok':False,'error':str(exc)})
            elif path == '/api/journal' or path.startswith('/journal-images/'):
                try:
                    if path.startswith('/journal-images/'):
                        mime,data=journal.image(path.removeprefix('/journal-images/'))
                        self.send(200,mime,data)
                    else:
                        params=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                        if set(params)-{'id','q','category','order','page','character'} or any(len(v)!=1 for v in params.values()):
                            raise ValueError('Choose valid journal parameters.')
                        if 'id' in params:
                            if set(params)!={'id'}:raise ValueError('Provide one entry reference.')
                            self.json_response(200,{'ok':True,'entry':journal.get(params['id'][0])})
                        else:
                            result=journal.list(params.get('q',[''])[0],params.get('category',[''])[0],
                                                params.get('order',['newest'])[0],int(params.get('page',['0'])[0]),params.get('character',[''])[0])
                            self.json_response(200,{'ok':True,'result':result})
                except ValueError as exc:self.json_response(400,{'ok':False,'error':str(exc)})
                except LookupError as exc:self.json_response(404,{'ok':False,'error':str(exc)})
                except (OSError,sqlite3.Error):self.json_response(503,{'ok':False,'error':'Journal storage is unavailable.'})
            elif path == '/api/gear-planner':
                try:
                    params=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                    if set(params)-{'threshold'} or any(len(v)!=1 for v in params.values()):raise ValueError('Provide one planner threshold.')
                    with cache.lock:
                        group=json.loads(json.dumps(cache.groups.selected()))
                        known=tuple(dict.fromkeys([name for g in cache.groups.data['groups'] for name in g['members']]+list(cache.bots)))
                    result=planner.get(group,known,int(params.get('threshold',['5'])[0]))
                    self.json_response(200,{'ok':True,'result':result})
                except ValueError as exc:self.json_response(400,{'ok':False,'error':str(exc)})
                except DatabaseError as exc:self.json_response(503,{'ok':False,'error':str(exc)})
            elif path == '/api/models/config':
                self.json_response(200, {'ok': True, 'config': models.get_config()})
            elif path == '/api/model':
                try:
                    parameters = parse_qs(urlsplit(self.path).query)
                    if not set(APPEARANCE) <= set(parameters) or set(parameters)-set(APPEARANCE)-{'equipment','weapon_mode'} or any(len(v) != 1 for v in parameters.values()):
                        raise ValueError('Provide one saved appearance.')
                    appearance = {key: int(parameters[key][0]) for key in APPEARANCE}
                    equipment=parameters.get('equipment',['[]'])[0]
                    if len(equipment)>5000:raise ValueError('Equipped items too large')
                    equipment=json.loads(equipment)
                    self.json_response(200, models.get(appearance,equipment,parameters.get('weapon_mode',['melee'])[0]))
                except ValueError:
                    self.json_response(400, {'available': False, 'pending': False})
            elif path == '/api/quest-party':
                try:
                    params = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                    if 'id' not in params or set(params)-{'id','roster'} or any(len(v)!=1 for v in params.values()):
                        raise ValueError('Provide one quest ID and optional roster.')
                    roster=params.get('roster',['group'])[0]
                    if roster not in ('group','watch'):raise ValueError('Choose a group or Playerbot Watch roster.')
                    with cache.lock:
                        group = ({'id':'playerbot-watch','name':'Playerbot Watch','members':list(cache.bots)} if roster=='watch'
                                 else json.loads(json.dumps(cache.groups.selected())))
                    result = (quest_log.party_status(group,int(params['id'][0]),watch=True) if roster=='watch'
                              else quest_log.party_status(group,int(params['id'][0])))
                    self.json_response(200, {'ok':True, 'result':result})
                except ValueError as exc:
                    self.json_response(400, {'ok':False, 'error':str(exc)})
                except DatabaseError as exc:
                    self.json_response(503, {'ok':False, 'error':str(exc)})
            elif path in ('/api/quests', '/api/quest'):
                try:
                    params = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                    allowed = {'mode','name','q','page','class'} if path == '/api/quests' else {'mode','name','id','class'}
                    if set(params)-allowed or any(len(v)!=1 for v in params.values()):
                        raise ValueError('Provide one value per quest parameter.')
                    result = quest_log.get(mode=params.get('mode',['active'])[0], name=params.get('name',[''])[0],
                        search=params.get('q',[''])[0], page=int(params.get('page',['0'])[0]),
                        quest_id=int(params.get('id',['0'])[0]) if path == '/api/quest' else None,
                        class_id=int(params.get('class',['0'])[0]))
                    self.json_response(200, {'ok':True, 'result':result})
                except ValueError as exc:
                    self.json_response(400, {'ok':False, 'error':str(exc)})
                except LookupError as exc:
                    self.json_response(404, {'ok':False, 'error':str(exc)})
                except DatabaseError as exc:
                    self.json_response(503, {'ok':False, 'error':str(exc)})
            elif path == '/api/training':
                try:
                    params=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                    if 'name' not in params or set(params)-{'name','q','level','mode'} or any(len(v)!=1 for v in params.values()):
                        raise ValueError('Provide one character name and one value per filter.')
                    result=training.get(params['name'][0],params.get('q',[''])[0],params.get('level',[''])[0],params.get('mode',['upcoming'])[0])
                    self.json_response(200,{'ok':True,'result':result})
                except ValueError as exc:self.json_response(400,{'ok':False,'error':str(exc)})
                except LookupError as exc:self.json_response(404,{'ok':False,'error':str(exc)})
                except DatabaseError as exc:self.json_response(503,{'ok':False,'error':str(exc)})
            elif path == '/api/item-tooltip':
                try:
                    params=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                    if set(params)!={'id'} or len(params['id'])!=1:raise ValueError('Provide one item ID.')
                    self.json_response(200,{'ok':True,'item':item_tooltips.get(int(params['id'][0]))})
                except ValueError as exc:self.json_response(400,{'ok':False,'error':str(exc)})
                except LookupError as exc:self.json_response(404,{'ok':False,'error':str(exc)})
                except DatabaseError as exc:self.json_response(503,{'ok':False,'error':str(exc)})
            elif path in ('/api/skills','/api/professions'):
                try:
                    params=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                    allowed={'names'} if path=='/api/skills' else {'name','skill'}
                    if set(params)!=allowed or any(len(v)!=1 for v in params.values()):
                        raise ValueError('Provide one value per skill parameter.')
                    names=params['names'][0].split(',') if path=='/api/skills' else [params['name'][0]]
                    result=skills.get(names,int(params['skill'][0]) if path=='/api/professions' else None)
                    self.json_response(200,{'ok':True,'result':result})
                except ValueError as exc:self.json_response(400,{'ok':False,'error':str(exc)})
                except LookupError as exc:self.json_response(404,{'ok':False,'error':str(exc)})
                except DatabaseError as exc:self.json_response(503,{'ok':False,'error':str(exc)})
            elif path in ('/api/auctions', '/api/auctions/item'):
                try:
                    params = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                    result = auctions.get(params, detail=path.endswith('/item'))
                    self.json_response(200, {'ok':True, 'result':result})
                except ValueError as exc:self.json_response(400, {'ok':False, 'error':str(exc)})
                except DatabaseError as exc:self.json_response(503, {'ok':False, 'error':str(exc)})
            elif path == '/api/armory/space':
                try:
                    params = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                    if set(params) != {'names'} or len(params['names']) != 1:
                        raise ValueError('Provide one list of character names.')
                    self.json_response(200, {'ok':True, 'space':armory.bag_space(params['names'][0].split(','))})
                except ValueError as exc:
                    self.json_response(400, {'ok':False, 'error':str(exc)})
                except DatabaseError as exc:
                    self.json_response(503, {'ok':False, 'error':str(exc)})
            elif path == '/api/armory':
                try:
                    name = parse_qs(urlsplit(self.path).query).get('name', [''])[0]
                    self.json_response(200, {'ok': True, 'inventory': armory.get(name)})
                except ValueError as exc:
                    self.json_response(400, {'ok': False, 'error': str(exc)})
                except LookupError as exc:
                    self.json_response(404, {'ok': False, 'error': str(exc)})
                except DatabaseError as exc:
                    self.json_response(503, {'ok': False, 'error': str(exc)})
            elif path.startswith('/icons/') and path.endswith('.jpg'):
                try:
                    self.send(200, 'image/jpeg', armory.icon(path[7:-4]))
                except LookupError:
                    self.send(404, 'text/plain', b'Icon unavailable')
            elif path == '/api/settings':
                self.json_response(200, {'ok': True, 'settings': settings.get()})
            elif path == '/api/server-identity':
                self.json_response(200, identity.get())
            elif path == '/api/session':
                self.json_response(200, {'token': token, 'bots': list(cache.bots), 'groups': cache.groups.data, 'notes':cache.notes.get(),'note_images':cache.notes.get_images()})
            elif path == '/api/sql/catalog':
                try:
                    self.json_response(200, {'ok': True, 'tables': console.catalog()})
                except QueryError as exc:
                    self.json_response(503, {'ok': False, 'error': str(exc)})
            elif path == '/api/characters':
                # Names only; no account/auth records. Search is escaped to a UTF-8 hex literal.
                parameters = parse_qs(urlsplit(self.path).query)
                term = parameters.get('q', [''])[0]
                if not re.fullmatch(r'[A-Za-z]{0,12}', term):
                    self.json_response(400, {'ok': False, 'error': 'Search with up to 12 letters.'})
                    return
                literal = '0x' + (term + '%').encode().hex()
                query = ('SELECT name,level,class,online FROM acore_characters.characters '
                         f'WHERE deleteDate IS NULL AND name LIKE {literal} ORDER BY name LIMIT 40')
                try:
                    self.json_response(200, {'ok': True, 'characters': console.executor(query)['rows']})
                except QueryError as exc:
                    self.json_response(503, {'ok': False, 'error': str(exc)})
            elif path == '/api/activity':
                try:
                    params=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                    if set(params)-{'view','character','kind','offset'} or any(len(v)!=1 for v in params.values()):
                        raise ValueError('Provide one value per activity filter.')
                    result=cache.activity(params.get('view',['party'])[0],params.get('character',[''])[0],
                        params.get('kind',[''])[0],int(params.get('offset',['0'])[0]))
                    self.json_response(200,{'ok':True,'activity':result})
                except ValueError as exc:self.json_response(400,{'ok':False,'error':str(exc)})
            elif path == '/api/snapshot':
                result = cache.get()
                body = json.dumps(result, ensure_ascii=False).encode('utf-8')
                self.send(200 if result['ok'] else 503, 'application/json; charset=utf-8', body)
            elif path in ASSETS:
                filename, mime = ASSETS[path]
                self.send(200, mime, (ROOT / 'static' / filename).read_bytes())
            else:
                self.send(404, 'text/plain', b'Not found')

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    try:
        network_file = ROOT / 'network.json'
        network = json.loads(network_file.read_text()) if network_file.exists() else {}
        if not isinstance(network,dict) or set(network)-{'listen','allowed_hosts'}:
            raise ValueError('Unknown network option')
        listen = str(ipaddress.IPv4Address(network.get('listen','127.0.0.1')))
        hosts = network.get('allowed_hosts',[])
        if not isinstance(hosts,list) or len(hosts)>16:
            raise ValueError('Invalid allowed hosts')
        hosts = [str(ipaddress.IPv4Address(h)) for h in hosts]
    except (OSError,ValueError,TypeError):
        parser.error('Cannot read network.json; provide an IPv4 listen address and allowed_hosts list.')
    parser.add_argument('--listen', default=listen, help='IPv4 listener; default from network.json or 127.0.0.1')
    parser.add_argument('--allow-host', action='append', default=hosts, help='Additional permitted IPv4 address in browser URLs')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--bots', default=None, help='Comma-separated Playerbot watch names; initially empty')
    parser.add_argument('--source', choices=['mysql', 'live'], default='mysql')
    parser.add_argument('--live-url', default='http://127.0.0.1:8767/v1/quests')
    parser.add_argument('--check', action='store_true', help='Read the live database once and print a safe summary')
    args = parser.parse_args()
    try:
        args.listen = str(ipaddress.IPv4Address(args.listen))
        args.allow_host = [str(ipaddress.IPv4Address(h)) for h in args.allow_host]
        if any(ipaddress.IPv4Address(h).is_unspecified for h in args.allow_host):
            raise ValueError('Use a concrete browser address')
    except ValueError:
        parser.error('Use IPv4 addresses for --listen and --allow-host; allowed hosts must be concrete addresses.')
    if not 1024 <= args.port <= 65535 or args.port in (3306, 3724, 3725, 8085, 8086):
        parser.error('Choose an unused dashboard port from 1024–65535, excluding database and game ports')
    watch_file = ROOT / 'watchlist.json'
    try:
        configured = json.loads(watch_file.read_text()) if watch_file.exists() else []
        bots = args.bots.split(',') if args.bots is not None else configured
        if not isinstance(bots, list):
            raise ValueError('Watch list must be a list of names')
    except (ValueError, OSError):
        parser.error('Cannot read watchlist.json; restore a valid list of character names.')
    bots = tuple(dict.fromkeys(n.strip() for n in bots if isinstance(n, str) and n.strip()))
    if len(bots) > 32:
        parser.error('Choose up to 32 Playerbot watch names')
    try:
        if bots:
            name_filter('c', bots)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        source = HttpQuestSource(args.live_url) if args.source == 'live' else MySQLSource()
    except ValueError as exc:
        parser.error(str(exc))
    try:
        cache = SnapshotCache(bots, source=source, watch_file=watch_file, groups_file=ROOT / 'groups.json', history_file=ROOT / 'activity.sqlite3', locations=LocationProvider(), notes_file=ROOT / 'watch-notes.json')
    except (ValueError, OSError) as exc:
        parser.error('Cannot load dashboard configuration: ' + str(exc))
    if args.check:
        result = cache.get()
        if not result['ok']:
            parser.exit(1, result['error'] + '\n')
        for name, view in result['snapshot']['views'].items():
            print(name + ': ' + json.dumps(view['summary']))
        print('Quest source: ' + result['snapshot']['source']['label'] + '; server configuration unchanged.')
        return
    try:
        try:
            settings = SettingsStore(ROOT / 'settings.json')
        except (ValueError, OSError):
            parser.exit(1, 'Cannot read settings.json. Restore a valid settings file before starting.\n')
        with ThreadingHTTPServer((args.listen, args.port), handler(cache, args.port, settings=settings, allowed_hosts=args.allow_host, journal=JournalStore(ROOT/'journal.sqlite3'))) as server:
            print(f'AzerothCore Journey Hub → http://localhost:{args.port}', flush=True)
            for host in args.allow_host:
                print(f'Allowed address → http://{host}:{args.port}', flush=True)
            print(f'Listening on {args.listen} · read-only MySQL · Ctrl+C to stop', flush=True)
            try:
                with registered(ROOT,server,sys.argv[1:]):server.serve_forever()
            except KeyboardInterrupt:
                print('\nDashboard stopped. WoW server unaffected.', flush=True)
    except (OSError,sqlite3.Error):
        parser.exit(1, 'Cannot bind the dashboard address/port. Check for an existing dashboard or choose --listen/--port.\n')


if __name__ == '__main__':
    main()
