"""Archive public TBC Anniversary realm and regional pricing CSVs."""
import csv
from datetime import datetime
import gzip
import io
import json
import logging
import math
from pathlib import Path
import tempfile
import time
from urllib.request import Request, urlopen

BASE = 'https://public-data.tradeskillmaster.com/classic/eu-fresh/'
FEEDS = {
    'anniversary_alliance': ('Thunderstrike EU Alliance', BASE+'realm/thunderstrike-alliance/items.csv', 12),
    'anniversary_region': ('EU Anniversary regional sales', BASE+'region/items.csv', 48),
}
HOUR = 3600_000
LIMIT = 8 * 1024 * 1024


def atomic(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temp = Path(output.name)
        try:
            output.write(data)
            output.flush()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def parse(raw, key):
    rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    if not rows:
        raise ValueError('Empty Anniversary CSV.')
    expected = {'itemId','marketValue','updatedAt'}
    expected |= {'minBuyout'} if key=='anniversary_alliance' else {'avgSalePrice','saleRate','soldPerDay'}
    if not expected.issubset(rows[0]):
        raise ValueError('Unexpected Anniversary CSV columns.')
    stamps = {row['updatedAt'] for row in rows}
    if len(stamps)!=1:
        raise ValueError('Inconsistent Anniversary scan time.')
    stamp = int(datetime.fromisoformat(stamps.pop().replace('Z','+00:00')).timestamp()*1000)
    if stamp <= 0 or stamp > int(time.time()*1000)+300_000:
        raise ValueError('Invalid Anniversary scan time.')
    indexed = {}
    for row in rows:
        if not row['itemId'].isascii() or not row['itemId'].isdecimal():
            continue
        item = int(row['itemId'])
        if 0 < item <= 4294967295:
            indexed[item] = row
    if not indexed:
        raise ValueError('No numeric Anniversary item IDs.')
    return stamp, indexed


def collect_anniversary(root):
    for key, (_, url, hours) in FEEDS.items():
        directory = root/'raw'/key
        directory.mkdir(parents=True,exist_ok=True)
        state_path = directory/'status.json'
        try:
            state = json.loads(state_path.read_text())
        except (OSError,ValueError):
            state = {}
        now = int(time.time()*1000)
        if now-state.get('attempted_at',0) < (3 if hours==12 else 12)*HOUR:
            continue
        state['attempted_at'] = now
        try:
            request = Request(url,headers={'User-Agent':'JourneyHub-market-preview/0.1','Accept':'text/csv'})
            with urlopen(request,timeout=20) as response:
                raw = response.read(LIMIT+1)
            if len(raw)>LIMIT:
                raise ValueError('Anniversary CSV exceeds size limit.')
            stamp, rows = parse(raw,key)
            archive = directory/f'{stamp}.csv.gz'
            if not archive.exists():
                atomic(archive,gzip.compress(raw,mtime=0))
            if stamp >= state.get('stamp',0):
                state.update(stamp=stamp,items=len(rows))
            state.pop('error',None)
        except (OSError, ValueError, KeyError, TypeError) as error:
            state['error'] = 'Fetch failed. Retaining the last archived CSV.'
            logging.getLogger('market-worker').warning('%s: %s',key,error)
        atomic(state_path,json.dumps(state).encode())


def feed_status(root, now):
    result={}
    for key,(label,url,hours) in FEEDS.items():
        try:
            state=json.loads((root/'raw'/key/'status.json').read_text())
        except (OSError,ValueError):
            state={}
        stamp=state.get('stamp')
        health='waiting' if not stamp else 'recent' if now-stamp<hours*HOUR else 'stale'
        result[key]=dict(state,label=label,health=health)
    return result


def realm_matches(root, query, limit=40):
    state = feed_status(root,int(time.time()*1000))['anniversary_alliance']
    if not state.get('stamp') or limit<=0:
        return []
    stamp=state['stamp']
    with gzip.open(root/'raw'/'anniversary_alliance'/f'{stamp}.csv.gz','rb') as source:
        _, rows=parse(source.read(LIMIT+1),'anniversary_alliance')
    term=query.casefold()
    return [(item,row['name']) for item,row in rows.items()
            if term==str(item) or term in row['name'].casefold()][:limit]


def fallback_prices(root, now, historical=False):
    status=feed_status(root,now)
    data={}
    for key,state in status.items():
        if 'stamp' not in state or (not historical and state['health']!='recent'):
            return {}
        with gzip.open(root/'raw'/key/f"{state['stamp']}.csv.gz",'rb') as handle:
            _,data[key]=parse(handle.read(LIMIT+1),key)
    realm=data['anniversary_alliance']
    region=data['anniversary_region']
    result={}
    for item,row in realm.items():
        if item not in region:
            continue
        sale=region[item]
        try:
            buyout=int(row['minBuyout'] or 0)
            market=int(row['marketValue'] or 0)
            sold=int(sale['avgSalePrice'] or 0)
            rate=float(sale['saleRate'] or 0)
            units=float(sale['soldPerDay'] or 0)
        except (KeyError,ValueError,TypeError):
            continue
        if buyout>0 and market>0 and sold>0 and .10<=rate<=1 and math.isfinite(units) and units>=3:
            result[item]=min(market,sold)
    return result
