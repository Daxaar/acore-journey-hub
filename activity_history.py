"""Durable observed changes, keyed by source and GUID, never inferred gameplay timestamps."""
import json
import sqlite3
import threading

EVENT_KINDS = ('level','entered','ready','status','objective','handin','left')


class ActivityHistory:
    def __init__(self, path=None):
        self.path = str(path) if path else ':memory:'
        self.lock = threading.Lock()
        self.connection = None
        self.error = None
        try:
            self.connection = sqlite3.connect(self.path, check_same_thread=False, timeout=2)
            self.connection.executescript('''
CREATE TABLE IF NOT EXISTS baselines (source TEXT NOT NULL, guid INTEGER NOT NULL, observed TEXT NOT NULL,
 state TEXT NOT NULL, PRIMARY KEY(source,guid));
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, source TEXT NOT NULL, guid INTEGER NOT NULL,
 name TEXT NOT NULL, observed TEXT NOT NULL, previous_observed TEXT NOT NULL, kind TEXT NOT NULL,
 quest INTEGER, title TEXT, message TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS event_character ON events(source,guid,id);
''')
            self.connection.commit()
        except sqlite3.Error:
            self.error = 'Activity history storage is unavailable; quest snapshots still work.'

    def observe(self, rows, source, observed):
        if self.error: return
        quests = {}
        rewards = {}
        for row in rows:
            if row['kind']=='quest':
                quests.setdefault(row['guid'],{})[str(row['id'])] = {
                    'status':row['status'],'title':row.get('title') or f"Quest #{row['id']}",
                    'labels':{**{f'mob{i}':row.get(f'objective_text{i}') or row.get(f'target_name{i}') or f'Target {i}' for i in range(1,5)},
                              **{f'item{i}':row.get(f'item_name{i}') or f'Collection {i}' for i in range(1,7)}},
                    'counts':{k:v for k,v in row.items() if k in ('explored','playercount') or
                              k in {f'mob{i}' for i in range(1,5)} or k in {f'item{i}' for i in range(1,7)}}}
            elif row['kind']=='rewarded':
                rewards.setdefault(row['guid'],{})[str(row['quest'])] = bool(row.get('active',1))
        with self.lock:
            db = self.connection
            try:
                with db:
                    for c in rows:
                        if c['kind']!='character' or not c.get('quest_state_available',True): continue
                        guid=c['guid']
                        current={'name':c['name'],'level':c['level'],'quests':quests.get(guid,{}),
                                 'rewards':rewards.get(guid,{}),'complete':bool(c.get('reward_history_complete'))}
                        previous=db.execute('SELECT observed,state FROM baselines WHERE source=? AND guid=?',(source,guid)).fetchone()
                        if previous:
                            before,raw=previous;old=json.loads(raw)
                            def event(kind,message,qid=None,title=None):
                                db.execute('INSERT INTO events(source,guid,name,observed,previous_observed,kind,quest,title,message) VALUES(?,?,?,?,?,?,?,?,?)',
                                    (source,guid,c['name'],observed,before,kind,qid,title,message))
                            if old['level']!=current['level']:
                                event('level',f"Level {old['level']} → {current['level']} observed")
                            handins=set()
                            if old['complete'] and current['complete']:
                                handins={qid for qid,active in current['rewards'].items() if
                                         qid not in old['rewards'] or (active and not old['rewards'][qid])}
                                for qid in sorted(handins,key=int):
                                    title=(old['quests'].get(qid) or current['quests'].get(qid) or {}).get('title',f'Quest #{qid}')
                                    event('handin','Hand-in record newly observed',int(qid),title)
                            for qid,q in current['quests'].items():
                                prior=old['quests'].get(qid)
                                if not prior:
                                    event('entered','Entered the saved quest log',int(qid),q['title']);continue
                                if q['status']!=prior['status']:
                                    label={1:'Ready to hand in',3:'In progress',5:'Failed'}.get(q['status'],'Status changed')
                                    event('ready' if q['status']==1 else 'status',label+' observed',int(qid),q['title'])
                                changes=[]
                                for key,value in q['counts'].items():
                                    prev=prior['counts'].get(key)
                                    if isinstance(prev,int) and isinstance(value,int) and value!=prev:
                                        label=('Target '+key[3:]) if key.startswith('mob') else ('Collection '+key[4:]) if key.startswith('item') else 'Event credit' if key=='explored' else 'PvP kills'
                                        label=q.get('labels',{}).get(key) or label
                                        changes.append(f'{label}: {prev} → {value}')
                                if changes:event('objective','; '.join(changes),int(qid),q['title'])
                            for qid,q in old['quests'].items():
                                if qid not in current['quests'] and qid not in handins:
                                    event('left','Left the saved quest log; reason unknown',int(qid),q['title'])
                        db.execute('INSERT OR REPLACE INTO baselines VALUES(?,?,?,?)',(source,guid,observed,json.dumps(current)))
                    db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 5000)')
                    db.execute('DELETE FROM baselines WHERE rowid NOT IN (SELECT rowid FROM baselines ORDER BY observed DESC LIMIT 512)')
            except (sqlite3.Error,ValueError,KeyError,TypeError):
                self.error='Activity history could not be saved; quest snapshots still work.'

    def get(self, guids, source, limit=50, offset=0, kind=None):
        if self.error or not guids: return {'events':[],'total':0,'warning':self.error}
        with self.lock:
            try:
                sql='source=? AND guid IN ('+','.join('?' for _ in guids)+')'
                args=[source,*guids]
                if kind:
                    sql+=' AND kind=?';args.append(kind)
                total=self.connection.execute('SELECT COUNT(*) FROM events WHERE '+sql,args).fetchone()[0]
                self.connection.row_factory=sqlite3.Row
                events=[dict(r) for r in self.connection.execute('SELECT * FROM events WHERE '+sql+' ORDER BY id DESC LIMIT ? OFFSET ?',args+[limit,offset])]
                self.connection.row_factory=None
                return {'events':events,'total':total,'warning':None,'offset':offset,'limit':limit}
            except sqlite3.Error:
                return {'events':[],'total':0,'warning':'Activity history could not be read.'}
