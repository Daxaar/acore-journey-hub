"""Opt-in control file shared with the module. Game database access remains read-only."""
import fcntl
import json
import os
from pathlib import Path
import tempfile
from armory import read_inventory_sql
from transactions import PREFIX

class TransactionMonitoring:
    def __init__(self,path=None,reader=read_inventory_sql):
        root=Path(__file__).resolve().parent
        config_path=root/'transaction-journal.json'
        config=json.loads(config_path.read_text()) if config_path.exists() else {}
        configured=path or os.environ.get('JOURNEY_HUB_TRANSACTION_MONITORING') or config.get('monitoring_file') or root/'transaction-monitoring.txt'
        self.path=Path(configured).expanduser()
        if not self.path.is_absolute():self.path=root/self.path
        self.reader=reader

    def enabled(self):
        try:
            text=self.path.read_text()
        except FileNotFoundError:
            return set()
        if len(text)>65536:
            raise ValueError('Monitoring file is too large.')
        return {int(part) for part in text.split() if part.isascii() and part.isdigit() and 0<int(part)<=4294967295}

    def characters(self,names,q=''):
        if not isinstance(q,str) or len(q)>100 or any(ord(c)<32 or 0xD800<=ord(c)<=0xDFFF for c in q):
            raise ValueError('Search with up to 100 printable characters.')
        selected=self.enabled()
        if q.strip():
            term='CONVERT(0x'+q.strip().encode().hex()+' USING utf8mb4)'
            condition=f'LOCATE({term},name)>0'
        else:
            if any(not name.isascii() or not name.isalpha() for name in names):
                raise ValueError('Invalid group character name.')
            literals=','.join("'"+n+"'" for n in names) or "''"
            ids=','.join(map(str,sorted(selected))) or '0'
            condition=f'name IN ({literals}) OR guid IN ({ids})'
        rows=self.reader(PREFIX+f"""
SELECT JSON_OBJECT('guid',guid,'name',name,'level',level,'class',class)
FROM acore_characters.characters WHERE {condition} ORDER BY name LIMIT 200;
COMMIT;
""")
        return {'characters':[{**row,'monitored':int(row['guid']) in selected} for row in rows],
                'enabled_count':len(selected),'limit':200}

    def participants(self):
        selected=self.enabled()
        ids=','.join(map(str,sorted(selected))) or '0'
        rows=self.reader(PREFIX+f"""
SELECT JSON_OBJECT('guid',c.guid,'name',c.name,'level',c.level,'class',c.class,
'has_history',EXISTS(SELECT 1 FROM acore_characters.transaction_journal WHERE actor_guid=c.guid OR counterparty_guid=c.guid),
'as_counterparty',EXISTS(SELECT 1 FROM acore_characters.transaction_journal WHERE counterparty_guid=c.guid))
FROM acore_characters.characters c
WHERE c.guid IN ({ids})
OR EXISTS(SELECT 1 FROM acore_characters.transaction_journal WHERE actor_guid=c.guid OR counterparty_guid=c.guid)
ORDER BY c.name;
COMMIT;
""")
        return [{**row,'monitored':int(row['guid']) in selected} for row in rows]

    def update(self,guid,enabled):
        if isinstance(guid,bool) or not isinstance(guid,int) or not 0<guid<=4294967295 or not isinstance(enabled,bool):
            raise ValueError('Provide a character GUID and monitoring switch.')
        rows=self.reader(PREFIX+f"SELECT JSON_OBJECT('guid',guid) FROM acore_characters.characters WHERE guid={guid};COMMIT;")
        if not rows:
            raise ValueError('Character no longer exists.')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            selected=self.enabled()
            if enabled:selected.add(guid)
            else:selected.discard(guid)
            if len(selected)>5000:raise ValueError('Monitor up to 5000 characters.')
            temporary=None
            try:
                with tempfile.NamedTemporaryFile(mode='w',dir=self.path.parent,delete=False) as output:
                    temporary=Path(output.name)
                    output.write(''.join(str(item)+chr(10) for item in sorted(selected)))
                    output.flush()
                    os.fsync(output.fileno())
                temporary.chmod(0o644)
                temporary.replace(self.path)
            finally:
                if temporary is not None:temporary.unlink(missing_ok=True)
        return {'guid':guid,'monitored':enabled,'enabled_count':len(selected)}
