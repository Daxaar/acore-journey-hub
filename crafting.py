"""Offline Classic crafting catalogue and dashboard-only, revisioned review decisions."""
from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import threading

ROOT = Path(__file__).resolve().parent
REVIEWS = ('not reviewed', 'approved', 'rejected', 'needs adjustment', 'deferred')
ASSESSMENTS = ('manual review', 'competitive — leave unchanged', 'strong — leave unchanged', 'adjustment proposed')
PROFESSIONS = {164: 'Blacksmithing', 165: 'Leatherworking', 197: 'Tailoring', 202: 'Engineering'}
SLOTS = {1:'Head',2:'Neck',3:'Shoulders',4:'Shirt',5:'Chest',6:'Waist',7:'Legs',8:'Feet',9:'Wrists',10:'Hands',11:'Finger',12:'Trinket',13:'One-hand',14:'Shield',15:'Ranged',16:'Back',17:'Two-hand',19:'Tabard',20:'Robe',21:'Main hand',22:'Off hand',23:'Held in off-hand',25:'Thrown',26:'Ranged',28:'Relic'}


def fingerprint(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def differences(baseline, proposed):
    return {k: {'original': baseline.get(k), 'proposed': v, 'difference': v-baseline[k]}
            for k, v in proposed.items() if v != baseline.get(k) and isinstance(v, (int, float)) and isinstance(baseline.get(k), (int, float))}


class ReviewConflict(ValueError):
    pass


class CraftingCatalogue:
    def __init__(self, root=ROOT, path=None):
        self.root = Path(root)
        self.path = Path(path) if path else self.root/'crafting-reviews.sqlite3'
        self.lock = threading.RLock()
        self.loaded = None
        self.data = {'records': [], 'provenance': {}}
        try:
            self.icons=json.loads((self.root/'assets/item-metadata.json').read_text()).get('icons',{})
        except (OSError,ValueError):
            self.icons={}

    def tooltip(self, item):
        fields=['armor','block','bonding','description','dmg_min1','dmg_max1','dmg_min2','dmg_max2','delay','ContainerSlots','MaxDurability']
        fields += [key+str(i) for i in range(1,11) for key in ('stat_type','stat_value')]
        return {**{k:item.get(k,0) for k in fields},'id':item['entry'],'name':item['name'],
                'quality':item.get('Quality',1),'level':item.get('ItemLevel'),
                'required_level':item.get('RequiredLevel',0),'required_skill':item.get('RequiredSkill',0),
                'skill_rank':item.get('RequiredSkillRank',0),'sell_price':item.get('SellPrice',0),
                'icon':self.icons.get(str(item.get('displayid')))}

    def dataset(self):
        p = self.root/'assets'/'crafting-catalogue.json'
        if not p.exists():
            return {'records': [], 'provenance': {}, 'available': False}
        stamp = (p.stat().st_mtime_ns, p.stat().st_size)
        with self.lock:
            if stamp != self.loaded:
                d = json.loads(p.read_text())
                if d.get('format') != 1 or not isinstance(d.get('records'), list):
                    raise ValueError('Unsupported crafting catalogue. Regenerate the local assets.')
                if len(d['records']) > 10000 or len({r['id'] for r in d['records']}) != len(d['records']):
                    raise ValueError('Invalid crafting catalogue identifiers or size.')
                self.data, self.loaded = d, stamp
            return {**self.data, 'available': True}

    @contextmanager
    def connect(self):
        # Never connect to the game database. Lazy creation preserves clean installation reads.
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript('''CREATE TABLE IF NOT EXISTS reviews (
          item INTEGER PRIMARY KEY, status TEXT NOT NULL, notes TEXT NOT NULL, revision INTEGER NOT NULL,
          dataset TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS review_history (
          event INTEGER PRIMARY KEY, item INTEGER NOT NULL, status TEXT NOT NULL, notes TEXT NOT NULL,
          revision INTEGER NOT NULL, dataset TEXT NOT NULL, updated TEXT NOT NULL,
          UNIQUE(item,revision));''')
        try:
            with db:
                yield db
        finally:
            db.close()

    def review_map(self):
        if not self.path.exists(): return {}
        with self.connect() as db:
            return {r['item']: dict(r) for r in db.execute('SELECT * FROM reviews')}

    @staticmethod
    def attach(record, reviews):
        review = reviews.get(record['id'], {'status':'not reviewed','notes':'','revision':0,'dataset':record['fingerprint'],'updated':None})
        return {**record, 'review':{**review, 'stale':review['dataset'] != record['fingerprint']},
                'differences':differences(record['baseline'],record['proposed'])}

    def get(self, params):
        allowed = {'q','profession','min','max','slot','quality','type','assessment','review','scope','panel','page','id'}
        if set(params)-allowed or any(len(v)!=1 for v in params.values()):
            raise ValueError('Provide one value per crafting filter.')
        p = {k:v[0] for k,v in params.items()}
        data = self.dataset()
        with self.lock:
            reviews = self.review_map()
        if 'id' in p:
            if set(p) != {'id'}: raise ValueError('Provide only the item ID for details.')
            entry = int(p['id'])
            row = next((r for r in data['records'] if r['id']==entry),None)
            if row is None: raise LookupError('Crafted item not found in this catalogue.')
            history=[]
            if self.path.exists():
                with self.connect() as db:
                    history = [dict(r) for r in db.execute('SELECT status,notes,revision,dataset,updated FROM review_history WHERE item=? ORDER BY revision DESC LIMIT 50',(entry,))]
            item=self.attach(row,reviews)
            item['tooltip']=self.tooltip(row['baseline'])
            item['comparators']=[{**c,'tooltip':self.tooltip(c['baseline'])} for c in row.get('comparators',[])]
            return {'item':item,'history':history,'provenance':data['provenance']}
        low,high,page = int(p.get('min') or 1),int(p.get('max') or 60),int(p.get('page') or 0)
        if p.get('panel') not in (None,'','focused'):raise ValueError('Choose a valid assessment panel.')
        if not 1<=low<=high<=60 or not 0<=page<=1000 or len(p.get('q',''))>100:
            raise ValueError('Choose levels 1–60 and a valid page/search.')
        for key,options in [('profession',{str(x) for x in PROFESSIONS}),('slot',{str(x) for x in SLOTS}),('quality',{str(x) for x in range(8)}),('assessment',set(ASSESSMENTS)),('review',set(REVIEWS)|{'stale'}),('scope',{'initial','future','endgame'}),('type',{'weapon','cloth','leather','mail','plate','shield','other'})]:
            if p.get(key) and p[key] not in options: raise ValueError('Choose a valid '+key+'.')
        rows = []
        for raw in data['records']:
            r = self.attach(raw,reviews)
            if p.get('panel')=='focused' and not r.get('focused_panel'):continue
            if not low<=max(1,r['baseline']['RequiredLevel'])<=high: continue
            if p.get('q') and p['q'].casefold() not in (r['name']+' '+str(r['id'])).casefold(): continue
            if any(p.get(k) and p[k]!=str(r[k]) for k in ('slot','quality','type','assessment','scope')): continue
            if p.get('profession') and int(p['profession']) not in [x['profession'] for x in r['recipes']]: continue
            if p.get('review') and not (r['review']['stale'] if p['review']=='stale' else r['review']['status']==p['review']): continue
            rows.append(r)
        counts = {k:sum(r['assessment']==k for r in data['records']) for k in ASSESSMENTS}
        # Details are fetched separately: list responses stay small.
        keys = ('id','name','slot','quality','type','assessment','scope','availability','review','recipes','fingerprint')
        return {'available':data['available'],'total':len(rows),'catalogue_total':len(data['records']),
                'page':page,'pages':(len(rows)+39)//40,'counts':counts,'provenance':data['provenance'],
                'items':[{**{k:r[k] for k in keys if k!='recipes'},'recipes':[{k:x[k] for k in ('id','name','profession','required_skill')} for x in r['recipes']],
                          'equip_level':r['baseline']['RequiredLevel'],'tooltip':self.tooltip(r['baseline'])} for r in rows[page*40:(page+1)*40]]}

    def save(self, payload):
        if set(payload)!={'id','status','notes','revision','fingerprint'}:
            raise ValueError('Provide an item, decision, notes, revision and catalogue fingerprint.')
        entry,status,notes,revision = (payload[k] for k in ('id','status','notes','revision'))
        if type(entry)is not int or type(revision)is not int or revision<0 or status not in REVIEWS or not isinstance(notes,str) or len(notes)>5000 or '\x00' in notes:
            raise ValueError('Choose a valid decision and notes up to 5,000 characters.')
        record = next((r for r in self.dataset()['records'] if r['id']==entry),None)
        if not record: raise LookupError('Crafted item not found.')
        if payload['fingerprint'] != record['fingerprint']: raise ReviewConflict('Catalogue changed. Reload before reviewing.')
        now = datetime.now(timezone.utc).isoformat()
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM reviews WHERE item=?',(entry,)).fetchone()
            if (row['revision'] if row else 0)!=revision: raise ReviewConflict('Decision changed in another window. Reload before saving.')
            values = (entry,status,notes,revision+1,record['fingerprint'],now)
            db.execute('INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?,?)',values)
            db.execute('INSERT INTO review_history(item,status,notes,revision,dataset,updated) VALUES (?,?,?,?,?,?)',values)
        return {'status':status,'notes':notes,'revision':revision+1,'dataset':record['fingerprint'],'updated':now,'stale':False}
