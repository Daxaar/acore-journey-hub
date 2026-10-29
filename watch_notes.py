"""Dashboard-only character notes, independent of watch-list membership and game data."""
import json
from pathlib import Path
import threading
from mysql_access import name_filter

MAX_NOTE = 2000


def validate(name, text):
    if not isinstance(name,str):raise ValueError('Choose a character name using 2–12 letters.')
    name_filter('c',[name])
    if not isinstance(text,str) or len(text)>MAX_NOTE or any((ord(c)<32 and c not in '\n\r\t') or 0xD800<=ord(c)<=0xDFFF for c in text):
        raise ValueError('Write a note of up to 2,000 characters.')
    return name.capitalize(),text.strip()


class WatchNotes:
    def __init__(self,path=None):
        self.path=Path(path) if path else None
        self.lock=threading.Lock();self.notes={}
        if self.path and self.path.exists():
            data=json.loads(self.path.read_text())
            if not isinstance(data,dict):raise ValueError('watch-notes.json must contain character notes.')
            for name,text in data.items():
                key,value=validate(name,text)
                if key in self.notes:raise ValueError('Duplicate character name in watch-notes.json.')
                if value:self.notes[key]=value

    def get(self):
        with self.lock:return dict(self.notes)

    def save(self,name,text):
        key,value=validate(name,text)
        with self.lock:
            updated=dict(self.notes)
            if value:updated[key]=value
            else:updated.pop(key,None)
            if self.path:
                temporary=self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps(updated,ensure_ascii=False)+'\n')
                temporary.chmod(0o600);temporary.replace(self.path)
            self.notes=updated
            return {'name':key,'text':value}
