"""Queue journal-only deletions for the module, preserving the Hub's read-only SQL boundary."""
import fcntl
import json
from pathlib import Path
import re
import tempfile
import uuid
from armory import read_inventory_sql
from transactions import PREFIX

class TransactionDeletion:
    def __init__(self,monitoring_path,reader=read_inventory_sql):
        self.folder=Path(monitoring_path).parent/'transaction-journal-requests'
        self.reader=reader

    def preview(self,guid):
        if isinstance(guid,bool) or not isinstance(guid,int) or not 0<guid<=4294967295:
            raise ValueError('Choose a character.')
        rows=self.reader(PREFIX+f"""
SELECT JSON_OBJECT('name',c.name,'guid',c.guid,
'cutoff',COALESCE((SELECT MAX(id) FROM acore_characters.transaction_journal),0),
'count',(SELECT COUNT(*) FROM acore_characters.transaction_journal WHERE actor_guid=c.guid OR counterparty_guid=c.guid))
FROM acore_characters.characters c WHERE c.guid={guid};
COMMIT;
""")
        if not rows:raise ValueError('Character no longer exists.')
        snapshot={**rows[0],'ticket':uuid.uuid4().hex}
        self.folder.mkdir(parents=True,exist_ok=True)
        (self.folder/(snapshot['ticket']+'.preview')).write_text(json.dumps(snapshot))
        return snapshot

    def ticket(self,ticket):
        if not isinstance(ticket,str) or not re.fullmatch('[a-f0-9]{32}',ticket):
            raise ValueError('Invalid removal request.')
        path=self.folder/(ticket+'.preview')
        try:return json.loads(path.read_text())
        except (FileNotFoundError,ValueError):raise ValueError('Removal request expired. Select the character again.')

    def confirm(self,ticket):
        snapshot=self.ticket(ticket)
        with (self.folder/'requests.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if not any((self.folder/(ticket+suffix)).exists() for suffix in ('.request','.working','.done')):
                if not snapshot['count']:
                    (self.folder/(ticket+'.done')).write_text('ok')
                else:
                    temporary=None
                    try:
                        with tempfile.NamedTemporaryFile(mode='w',dir=self.folder,delete=False) as output:
                            temporary=Path(output.name)
                            output.write(f"{snapshot['guid']} {snapshot['cutoff']}\n")
                        temporary.chmod(0o644)
                        temporary.replace(self.folder/(ticket+'.request'))
                    finally:
                        if temporary is not None:temporary.unlink(missing_ok=True)
        return self.status(ticket)

    def status(self,ticket):
        snapshot=self.ticket(ticket)
        done=self.folder/(ticket+'.done')
        state='pending'
        if done.exists():state='complete' if done.read_text().strip()=='ok' else 'failed'
        return {'ticket':ticket,'state':state,'name':snapshot['name'],'count':snapshot['count']}
