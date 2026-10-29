"""Cached public realm label and the machine hosting this dashboard."""
from connection import env
import os
import socket
import threading
import time

from mysql_access import DatabaseError
from prepare_profession_assets import query


class ServerIdentity:
    def __init__(self, reader=None):
        self.reader = reader or query
        self.lock = threading.Lock()
        self.expires = 0
        self.realm = 'Realm unavailable'

    def get(self):
        with self.lock:
            if time.monotonic() >= self.expires:
                self.realm = 'Realm unavailable'
                try:
                    realm_id = env('REALM_ID', '')
                    if realm_id and (not realm_id.isascii() or not realm_id.isdecimal() or not 1 <= int(realm_id) <= 4294967295):
                        raise ValueError('Invalid realm ID')
                    condition = ' WHERE id=' + str(int(realm_id)) if realm_id else ''
                    rows = self.reader("SELECT JSON_OBJECT('name',name) FROM acore_auth.realmlist" + condition + ' ORDER BY id LIMIT 2;')
                    if len(rows) == 1 and isinstance(rows[0].get('name'), str) and rows[0]['name'].strip():
                        self.realm = rows[0]['name'].strip()[:120]
                    elif len(rows) > 1:
                        self.realm = 'Multiple realms: set CHARACTER_HUB_REALM_ID'
                except (DatabaseError, ValueError, TypeError, KeyError):
                    pass
                self.expires = time.monotonic() + 60
            return {'realm': self.realm, 'host': env('HOST_NAME') or socket.gethostname()}
