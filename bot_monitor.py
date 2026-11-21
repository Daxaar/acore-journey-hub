"""Read a shared live snapshot and control the optional exporter. No game database access."""
import fcntl
import json
import os
from pathlib import Path
import tempfile
import threading
import time

BOT_TYPES=('human','random_bot','alt_bot','unknown_bot')
DEFAULT_CONTROL={'enabled':False,'interval_ms':5000,'include_quests':True}

class BotMonitor:
    def __init__(self,directory=None,classes=None,races=None,clock=None):
        root=Path(__file__).resolve().parent
        config=root/'bot-monitor.json'
        local=json.loads(config.read_text()) if config.exists() else {}
        configured=directory or os.environ.get('JOURNEY_HUB_BOT_MONITOR_DIRECTORY') or local.get('directory')
        self.directory=Path(configured).expanduser() if configured else None
        if self.directory is not None and not self.directory.is_absolute():self.directory=root/self.directory
        self.classes=classes or {}
        self.races=races or {}
        self.clock=clock or (lambda:int(time.time()*1000))
        self.lock=threading.Lock()
        self.cached_key=None
        self.cached=None
        self.cached_size=0
        self.xp_sessions = {}
        self.xp_frame = None

    def control(self):
        if self.directory is None:return dict(DEFAULT_CONTROL)
        try:
            text=(self.directory/'control.txt').read_text()
        except FileNotFoundError:return dict(DEFAULT_CONTROL)
        parts=text.split()
        if len(parts)!=3 or parts[0] not in ('0','1') or parts[2] not in ('0','1'):
            raise ValueError('The exporter control file is invalid.')
        try:interval=int(parts[1])
        except ValueError:raise ValueError('The exporter interval is invalid.')
        if not 1000<=interval<=60000:raise ValueError('The exporter interval is invalid.')
        return {'enabled':parts[0]=='1','interval_ms':interval,'include_quests':parts[2]=='1'}

    def update(self,payload):
        if self.directory is None or not self.directory.is_dir():
            raise ValueError('Configure the shared Bot Monitor directory before enabling capture.')
        if set(payload)!={'enabled','interval_ms','include_quests'}:
            raise ValueError('Provide capture, interval and quest settings.')
        if not isinstance(payload['enabled'],bool) or not isinstance(payload['include_quests'],bool):
            raise ValueError('Choose valid capture and quest switches.')
        interval=payload['interval_ms']
        if isinstance(interval,bool) or not isinstance(interval,int) or not 1000<=interval<=60000:
            raise ValueError('Choose an interval from 1 to 60 seconds.')
        with (self.directory/'control.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            temporary=None
            try:
                with tempfile.NamedTemporaryFile(mode='w',dir=self.directory,delete=False) as output:
                    temporary=Path(output.name)
                    output.write(f"{int(payload['enabled'])} {interval} {int(payload['include_quests'])}"+chr(10))
                    output.flush()
                    os.fsync(output.fileno())
                temporary.chmod(0o644)
                temporary.replace(self.directory/'control.txt')
            finally:
                if temporary is not None:temporary.unlink(missing_ok=True)
        return dict(payload)

    def _observe_xp(self, snapshot):
        """Track only the latest observed session per online character."""
        now = snapshot['generated_at_ms']
        boot = snapshot.get('exporter_boot_at_ms')
        frame = (boot, now, snapshot.get('sequence'))
        if frame == self.xp_frame:
            return
        if self.xp_frame is not None and boot == self.xp_frame[0] and now < self.xp_frame[1]:
            return
        current = {}
        for row in snapshot['characters'] if snapshot.get('enabled') else ():
            guid, started, level, xp, next_xp = (
                row.get(k) for k in ('guid', 'session_started_at', 'level', 'xp', 'next_level_xp')
            )
            if not all(type(v) is int and v >= 0 for v in (guid, started, level, xp, next_xp)) or not started:
                continue
            identity = (boot, started)
            first, gained, partial = now, 0, False
            previous = self.xp_sessions.get(guid)
            if previous and previous[0] == identity:
                _, first, old_level, old_xp, old_next, gained, partial = previous
                if level == old_level and xp >= old_xp:
                    gained += xp - old_xp
                elif level == old_level + 1 and old_next > old_xp:
                    gained += old_next - old_xp + xp
                else:
                    # A skipped level or an external XP reset cannot be reconstructed from these snapshots.
                    partial = True
            current[guid] = (identity, first, level, xp, next_xp, gained, partial)
            row['observed_xp_gained'] = gained
            row['xp_observed_seconds'] = max(0, (now - first) // 1000)
            row['xp_partial'] = partial
        self.xp_sessions = current
        self.xp_frame = frame

    def snapshot(self):
        if self.directory is None:return None
        path=self.directory/'snapshot.json'
        with self.lock:
            try:
                with path.open('rb') as source:
                    stat=os.fstat(source.fileno())
                    key=(stat.st_ino,stat.st_mtime_ns,stat.st_size)
                    if key==self.cached_key:return self.cached
                    if stat.st_size>32*1024*1024:raise ValueError('The live snapshot exceeds the supported size.')
                    data=json.load(source)
            except FileNotFoundError:return None
            if not isinstance(data,dict) or data.get('schema_version')!=1 or not isinstance(data.get('characters'),list):
                raise ValueError('Unsupported Bot Monitor snapshot.')
            if not isinstance(data.get('generated_at_ms'),int) or not isinstance(data.get('interval_ms'),int):
                raise ValueError('Invalid Bot Monitor timestamp or interval.')
            self._observe_xp(data)
            self.cached_key=key
            self.cached=data
            self.cached_size=stat.st_size
            return data

    def get(self,params):
        allowed={'zone','map','q','type','faction','min','max','positions'}
        if set(params)-allowed or any(len(value)!=1 for value in params.values()):
            raise ValueError('Provide one value per Live World filter.')
        values={key:value[0] for key,value in params.items()}
        positions = values.get('positions', '0')
        if positions not in ('0', '1'):
            raise ValueError('Positions must be 0 or 1.')
        query=values.get('q','').strip()
        if len(query)>100 or any(ord(c)<32 or 0xD800<=ord(c)<=0xDFFF for c in query):
            raise ValueError('Search with up to 100 printable characters.')
        kind=values.get('type','')
        faction=values.get('faction','')
        if kind and kind not in BOT_TYPES:raise ValueError('Choose a valid character type.')
        if faction and faction not in ('Alliance','Horde'):raise ValueError('Choose a valid faction.')
        minimum=int(values.get('min') or 1)
        maximum=int(values.get('max') or 80)
        if not 1<=minimum<=maximum<=80:raise ValueError('Choose a level range from 1 to 80.')
        selected=None
        if 'zone' in values or 'map' in values:
            if 'zone' not in values or 'map' not in values:raise ValueError('Choose a map and zone together.')
            selected=(int(values['map']),int(values['zone']))
            if any(not 0<=value<=4294967295 for value in selected):raise ValueError('Choose valid map and zone IDs.')
        control=self.control()
        result={'configured':self.directory is not None,'control':control,'state':'unconfigured','counts':None,
                'zones':[],'characters':[],'levels':[],'metadata':{},'age_ms':None,'file_size_bytes':0}
        if positions == '1':
            result['map_points'] = []
        if self.directory is None:return result
        snapshot=self.snapshot()
        result['state']='off' if not control['enabled'] else 'starting'
        if snapshot is None:return result
        age=max(0,self.clock()-snapshot['generated_at_ms'])
        result.update(age_ms=age,file_size_bytes=self.cached_size,
                      metadata={key:value for key,value in snapshot.items() if key!='characters'})
        if not control['enabled']:return result
        if not snapshot.get('enabled'):return result
        if age>max(15000,snapshot['interval_ms']*3):
            result['state']='stale'
            return result
        result['state']='running'
        counts={kind:0 for kind in BOT_TYPES}
        zones={}
        levels={}
        needle=query.casefold()
        for original in snapshot['characters']:
            row=dict(original)
            row['class_name']=self.classes.get(row.get('class'),'Class #'+str(row.get('class')))
            row['race_name']=self.races.get(row.get('race'),'Race #'+str(row.get('race')))
            if kind and row['bot_type']!=kind:continue
            if faction and row['faction']!=faction:continue
            if not minimum<=row['level']<=maximum:continue
            if needle and not any(needle in str(row.get(key,'')).casefold() for key in ('name','zone_name','area_name','map_name')):continue
            bot_type=row['bot_type'] if row['bot_type'] in BOT_TYPES else 'unknown_bot'
            counts[bot_type]+=1
            level_range='80' if row['level']==80 else '1–9' if row['level']<10 else str(row['level']//10*10)+'–'+str(row['level']//10*10+9)
            levels[level_range]=levels.get(level_range,0)+1
            key=(row['map_id'],row['zone_id'])
            zone=zones.setdefault(key,{'map_id':key[0],'zone_id':key[1],
                'name':row['zone_name'] or 'Unknown zone #'+str(key[1]),'map_name':row['map_name'],
                'human':0,'random_bot':0,'alt_bot':0,'unknown_bot':0,'total':0,'bots':0})
            zone[bot_type]+=1;zone['total']+=1
            if bot_type!='human':zone['bots']+=1
            if selected==key:result['characters'].append(row)
            if positions == '1':
                fields = ('guid','name','class','bot_type','map_id','zone_id','instance_id','x','y')
                result['map_points'].append({field: row.get(field) for field in fields})
        result['counts']={'total':sum(counts.values()),**counts}
        result['zones']=sorted(zones.values(),key=lambda zone:(-zone['bots'],zone['name'].casefold()))
        result['levels']=[{'range':label,'count':count} for label,count in sorted(levels.items(),key=lambda pair:int(pair[0].split('–')[0]))]
        result['characters'].sort(key=lambda row:row['name'].casefold())
        return result
