"""Source boundary: providers return canonical character/quest records, never rendered HTML."""
from connection import env

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import re
from typing import Protocol
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

from mysql_access import DatabaseError, name_filter, read_database


class SourceError(DatabaseError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise SourceError('Live API redirects are not accepted')


@dataclass
class Observation:
    rows: list
    observed_at: str
    source: dict


class QuestSource(Protocol):
    def fetch(self, names: tuple[str, ...]) -> Observation:
        """Return one observation for the requested names or raise SourceError. No silent fallback."""


class MySQLSource:
    def __init__(self, reader=read_database):
        self.reader = reader

    def fetch(self, names):
        rows = self.reader(names) if names else []
        return Observation(rows, datetime.now(timezone.utc).isoformat(), {
            'id': 'mysql', 'label': 'MySQL saved snapshots', 'live': False,
            'save_interval_seconds': 900, 'save_timestamp_available': False})


class HttpQuestSource:
    """Opt-in adapter for a future v1 read-only world API; does not enable anything in AzerothCore."""

    def __init__(self, url):
        parsed = urlsplit(url)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost')
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Live API URL must be a local http://127.0.0.1:PORT/path without credentials')
        self.url = url

    def fetch(self, names):
        name_filter('c', names)
        headers = {'Accept': 'application/json'}
        token = env('LIVE_TOKEN')
        if token:
            headers['Authorization'] = 'Bearer ' + token
        try:
            opener = build_opener(ProxyHandler({}), NoRedirect())
            with opener.open(Request(self.url + '?' + urlencode({'names': ','.join(names)}), headers=headers),
                             timeout=5) as response:
                body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError('Response too large')
            payload = json.loads(body)
            if payload['schema_version'] != 1 or not isinstance(payload['rows'], list):
                raise ValueError('Unsupported schema')
            observed = datetime.fromisoformat(payload['observed_at'])
            if observed.tzinfo is None or not -5 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 15:
                raise ValueError('Stale or invalid observation timestamp')
            rows = payload['rows']
            if len(rows) > 1500:
                raise ValueError('Too many records')
            requested = {name.casefold() for name in names}
            guids = set()
            for row in rows:
                if row['kind'] == 'character':
                    if row['name'].casefold() not in requested:
                        raise ValueError('Unrequested character')
                    for key in ('guid', 'class', 'race', 'level', 'xp', 'zone', 'online'):
                        if type(row[key]) is not int or row[key] < 0:
                            raise ValueError('Invalid character record')
                    row['quest_state_available'] = bool(row['online'])
                    guids.add(row['guid'])
            for row in rows:
                if row['kind'] not in ('character', 'quest', 'rewarded') or row['guid'] not in guids:
                    raise ValueError('Invalid record ownership')
                if row['kind'] == 'rewarded' and type(row['quest']) is not int:
                    raise ValueError('Invalid rewarded quest')
                if row['kind'] == 'quest':
                    if type(row['id']) is not int or row['status'] not in (1, 3, 5):
                        raise ValueError('Invalid quest')
                    for key, value in row.items():
                        numeric = re.fullmatch(r'(mob[1-4]|target[1-4]|target_count[1-4]|item[1-6]|'
                                               r'item_id[1-6]|item_count[1-6]|special_flags|explored|playercount|'
                                               r'player_kills|money_required|money|time_allowed|faction|'
                                               r'reputation_required|level)', key)
                        if numeric and value is not None and type(value) is not int:
                            raise ValueError('Invalid objective')
                    for key in ('title', 'description', 'area'):
                        if row.get(key) is not None and not isinstance(row[key], str):
                            raise ValueError('Invalid quest text')
                    if any(c['guid'] == row['guid'] and not c['online'] for c in rows if c['kind'] == 'character'):
                        raise ValueError('Offline character cannot supply live quest state')
            return Observation(rows, payload['observed_at'], {
                'id': 'world-api', 'label': 'Live world-server API', 'live': True,
                'save_interval_seconds': None, 'save_timestamp_available': False})
        except SourceError:
            raise
        except Exception as exc:
            message = 'Live quest API unavailable, stale, or incompatible; no MySQL fallback was used.'
            raise SourceError(message) from exc
