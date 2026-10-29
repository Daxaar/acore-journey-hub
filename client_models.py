"""Optional, bounded, read-only WotLK client mesh preview. No client files are served directly."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
import threading

ROOT = Path(__file__).resolve().parent
RACES = {1:'Human', 2:'Orc', 3:'Dwarf', 4:'NightElf', 5:'Scourge', 6:'Tauren', 7:'Gnome',
         8:'Troll', 10:'BloodElf', 11:'Draenei'}
APPEARANCE = ('race','gender','skin','face','hairStyle','hairColor','facialStyle')


def client_path(value):
    if not isinstance(value, str) or len(value) > 500 or any(ord(c) < 32 for c in value):
        raise ValueError('Enter a local Windows or Linux client folder path.')
    value = value.strip()
    if re.match(r'^[A-Za-z]:[\\/]', value):
        value = '/mnt/' + value[0].lower() + '/' + value[3:].replace('\\','/')
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or value.startswith('//'):
        raise ValueError('Use an absolute local folder path without parent-directory segments.')
    return path


def array(data, offset, fmt, limit):
    count, address = struct.unpack_from('<II', data, offset)
    size = struct.calcsize('<' + fmt)
    if count > limit or address + count * size > len(data):
        raise ValueError('Unsupported client array')
    return list(struct.iter_unpack('<' + fmt, data[address:address + count * size]))


def dbc(data, fields):
    magic, count, width, size, strings = struct.unpack_from('<4s4I', data)
    if magic != b'WDBC' or width != fields or size != fields * 4 or count > 100000 or len(data) != 20+count*size+strings:
        raise ValueError('Unsupported client DBC')
    block = data[20+count*size:]
    rows = list(struct.iter_unpack('<'+'I'*fields, data[20:20+count*size]))
    def string(offset):
        if offset >= len(block):
            raise ValueError('Invalid client string')
        end = block.find(b'\0', offset)
        if end < 0: raise ValueError('Invalid client string')
        return block[offset:end].decode('utf-8')
    return rows, string


class Archives:
    def __init__(self, root):
        sys.path.insert(0, str(ROOT / 'third_party'))
        from mpyq import MPQArchive
        self.archives = []
        data = root / 'Data'
        # Newest full WotLK patch wins, including localized DBC patches.
        files = [data / name for name in ('patch-3.MPQ','patch-2.MPQ','patch.MPQ')]
        locales = sorted(p for p in data.iterdir() if p.is_dir() and re.fullmatch('[a-z]{2}[A-Z]{2}', p.name))
        for locale in locales:
            files += [locale / name for name in (f'patch-{locale.name}-3.MPQ',f'patch-{locale.name}-2.MPQ',
                                                 f'patch-{locale.name}.MPQ',f'locale-{locale.name}.MPQ')]
        files += [data / name for name in ('lichking.MPQ','expansion.MPQ','common-2.MPQ','common.MPQ')]
        try:
            for file in files:
                if file.is_file():
                    # Bounds before the upstream reader allocates/decrypts archive tables.
                    with file.open('rb') as stream:
                        header = stream.read(32)
                    if len(header) != 32 or header[:4] != b'MPQ\x1a': continue
                    values = struct.unpack('<4sIIHHIIII', header)
                    if values[3] > 1 or values[4] > 8 or max(values[-2:]) > 1000000: continue
                    self.archives.append(MPQArchive(str(file), listfile=False))
        except Exception:
            self.close()
            raise

    def read(self, name):
        for archive in self.archives:
            entry = archive.get_hash_table_entry(name)
            if entry is None: continue
            if entry.block_table_index >= len(archive.block_table): raise ValueError('Invalid archive entry')
            block = archive.block_table[entry.block_table_index]
            if block.size > 16000000 or block.archived_size > 16000000: raise ValueError('Client asset too large')
            data = archive.read_file(name)
            if data is not None:
                if len(data) != block.size: raise ValueError('Incomplete client asset')
                return data
        raise ValueError('Client asset unavailable')

    def close(self):
        for archive in self.archives: archive.close()


def blp(data):
    """Decode the first mip of bounded BLP2 palette/DXT/BGRA textures into RGBA."""
    if len(data) < 148 or data[:4] != b'BLP2' or struct.unpack_from('<I',data,4)[0] != 1:
        raise ValueError('Unsupported client texture')
    encoding, depth, alpha = data[8:11]
    width,height = struct.unpack_from('<II',data,12)
    offset,size = struct.unpack_from('<I',data,20)[0],struct.unpack_from('<I',data,84)[0]
    if not 0 < width <= 1024 or not 0 < height <= 1024 or offset+size > len(data):
        raise ValueError('Invalid client texture size')
    raw = data[offset:offset+size]; pixels=width*height
    output=bytearray(pixels*4)
    if encoding == 1:
        if len(data)<1172 or len(raw)<pixels+(pixels*depth+7)//8 or depth not in (0,1,4,8):
            raise ValueError('Invalid palette texture')
        for i in range(pixels):
            b,g,r,_=data[148+raw[i]*4:152+raw[i]*4]
            a=255 if depth==0 else ((raw[pixels+i*depth//8] >> (i*depth%8)) & ((1<<depth)-1))*255//((1<<depth)-1)
            output[i*4:i*4+4]=bytes((r,g,b,a))
    elif encoding == 3:
        if len(raw)<pixels*4: raise ValueError('Invalid raw texture')
        for i in range(pixels):
            b,g,r,a=raw[i*4:i*4+4];output[i*4:i*4+4]=bytes((r,g,b,a))
    elif encoding == 2 and alpha in (0,1,7):
        blocksize=8 if alpha==0 else 16
        if len(raw)<((width+3)//4)*((height+3)//4)*blocksize: raise ValueError('Invalid DXT texture')
        def rgb(value): return ((value>>11)*255//31,((value>>5)&63)*255//63,(value&31)*255//31)
        index=0
        for by in range(0,height,4):
            for bx in range(0,width,4):
                block=raw[index:index+blocksize];index+=blocksize
                c0,c1,bits=struct.unpack_from('<HHI',block,blocksize-8)
                colors=[rgb(c0),rgb(c1)]
                if c0>c1 or alpha!=0:
                    colors += [tuple((2*a+b)//3 for a,b in zip(*colors)),tuple((a+2*b)//3 for a,b in zip(*colors))]
                else: colors += [tuple((a+b)//2 for a,b in zip(*colors)),(0,0,0)]
                if alpha==7:
                    a0,a1=block[:2];values=[a0,a1]
                    values += ([( (7-i)*a0+i*a1)//7 for i in range(1,7)] if a0>a1 else
                               [((5-i)*a0+i*a1)//5 for i in range(1,5)]+[0,255])
                    abits=int.from_bytes(block[2:8],'little')
                for i in range(16):
                    x,y=bx+i%4,by+i//4
                    if x>=width or y>=height: continue
                    color=(bits>>(2*i))&3;a=255
                    if alpha==0 and c0<=c1 and color==3 and depth: a=0
                    elif alpha==1: a=((int.from_bytes(block[:8],'little')>>(4*i))&15)*17
                    elif alpha==7: a=values[(abits>>(3*i))&7]
                    output[(y*width+x)*4:(y*width+x)*4+4]=bytes((*colors[color],a))
    else: raise ValueError('Unsupported client texture encoding')
    return width,height,output


def overlay(base, layer, region):
    width,height,pixels=base;sw,sh,source=layer
    # WotLK's body texture atlas uses 256x256 reference coordinates.
    rx,ry,rw,rh=region
    rx,ry,rw,rh=rx*width//256,ry*height//256,rw*width//256,rh*height//256
    for y in range(rh):
        for x in range(rw):
            pos=((ry+y)*width+rx+x)*4;sp=(min(sh-1,y*sh//rh)*sw+min(sw-1,x*sw//rw))*4
            a=source[sp+3]
            for c in range(3): pixels[pos+c]=(source[sp+c]*a+pixels[pos+c]*(255-a))//255
            pixels[pos+3]=255


def build_model(root, character):
    archives=Archives(root)
    try:
        race,gender=character['race'],character['gender']
        name=RACES[race]+('Female' if gender else 'Male')
        prefix='Character\\'+RACES[race]+'\\'+('Female' if gender else 'Male')+'\\'+name
        model=archives.read(prefix+'.m2');skin=archives.read(prefix+'00.skin')
        if model[:4]!=b'MD20' or struct.unpack_from('<I',model,4)[0]!=264 or skin[:4]!=b'SKIN':
            raise ValueError('Unsupported character model version')
        vertices=array(model,60,'3f4B4B3f2f2f',60000)
        if not vertices or any(not all(math.isfinite(v) for v in row[:3]+row[11:]) for row in vertices):
            raise ValueError('Invalid model coordinates')
        lookup=[r[0] for r in array(skin,4,'H',65535)]
        triangles=[r[0] for r in array(skin,12,'H',300000)]
        meshes=array(skin,28,'10H7f',500)
        sections,string=dbc(archives.read('DBFilesClient\\CharSections.dbc'),10)
        def section(kind,variation,color):
            return next((r for r in sections if r[1:4]==(race,gender,kind) and r[8:10]==(variation,color)),None)
        body=section(0,0,character['skin'])
        if not body: raise ValueError('Saved skin is unavailable in this client')
        texture=blp(archives.read(string(body[4])))
        # Underwear, face and scalp layers come from the supplied client, not external artwork.
        for kind,variation,color,regions,fields in [
            (4,0,character['skin'],[(128,96,128,64),(128,0,128,64)],[4,5]),
            (1,character['face'],character['skin'],[(0,192,128,64),(0,160,128,32)],[4,5]),
            (3,character['hairStyle'],character['hairColor'],[(0,192,128,64),(0,160,128,32)],[5,6])]:
            row=section(kind,variation,color)
            if row:
                for field,region in zip(fields,regions):
                    if row[field]:
                        try:layer=archives.read(string(row[field]))
                        except ValueError:
                            # Some stock Draenei scalp entries reference intentionally absent overlays.
                            if kind==3:continue
                            raise
                        overlay(texture,blp(layer),region)
        hair=section(3,character['hairStyle'],character['hairColor'])
        hair_rows,_=dbc(archives.read('DBFilesClient\\CharHairGeosets.dbc'),6)
        hair_geo=next((r[4] for r in hair_rows if r[1:4]==(race,gender,character['hairStyle'])),None)
        # Base body plus the selected hair. Unimplemented equipment geosets are deliberately omitted.
        selected={0,101,201,301,401,501,601,701,801,901,1001,1101,1301,1401,1601,1701,1801}
        if hair_geo is not None:selected.add(hair_geo)
        from equipment_models import apply_equipment
        posed,texture,selected,hair_geo,cape,attached=apply_equipment(
            archives,model,skin,vertices,character,texture,selected,hair_geo)
        indices=[];groups=[]
        for mesh in meshes:
            if mesh[0] not in selected:continue
            start=(mesh[1]<<16)+mesh[4];count=mesh[5]
            if start+count>len(triangles) or count%3:raise ValueError('Invalid skin geometry')
            begin=len(indices)
            for index in triangles[start:start+count]:
                if index>=len(lookup) or lookup[index]>=len(vertices):raise ValueError('Invalid skin vertex')
                indices.append(lookup[index])
            groups.append({'start':begin,'count':count,'hair':mesh[0]==hair_geo and hair_geo!=0,'geoset':mesh[0]})
        if not indices:raise ValueError('No base geometry')
        textures=[texture]
        if any(g['hair'] for g in groups):
            if not hair or not hair[4]:raise ValueError('Hair texture unavailable')
            textures.append(blp(archives.read(string(hair[4]))))
        hair_texture=1 if len(textures)>1 else None
        cape_texture=None
        if cape is not None:
            cape_texture=len(textures);textures.append(cape)
        for group in groups:
            group['texture']=hair_texture if group['hair'] else cape_texture if group['geoset']//100==15 else 0
            if group['texture'] is None:raise ValueError('Missing character material')
        attached_slots=[]
        for slot,component_vertices,component_indices,component_groups,component_textures in attached:
            vertex_offset=len(posed);index_offset=len(indices);texture_offset=len(textures)
            if vertex_offset+len(component_vertices)>65535:raise ValueError('Equipped preview too complex')
            posed.extend(component_vertices);indices.extend(index+vertex_offset for index in component_indices)
            groups.extend({'start':g['start']+index_offset,'count':g['count'],'texture':g['texture']+texture_offset}
                          for g in component_groups)
            textures.extend(component_textures);attached_slots.append(slot)
        return {'vertices':[[round(float(x),6) for x in row] for row in posed],
                'indices':indices,'groups':groups,
                'textures':[{'width':w,'height':h,'rgba':base64.b64encode(p).decode()} for w,h,p in textures],
                'label':name,'preview_kind':'equipped-client-model','attached_slots':attached_slots,
                'equipment':character.get('equipment',[]),'weapon_mode':character.get('weapon_mode','melee'),
                'note':'Saved equipment in a static standing pose. Enchantment effects, animation and custom guild-tabard artwork are not rendered.'}
    finally: archives.close()


class ClientModels:
    def __init__(self, root=ROOT, builder=build_model):
        self.root,self.builder=root,builder
        self.lock=threading.Lock();self.active=None;self.results={}
        try:
            self.config=self.validate(json.loads((root/'client-models.json').read_text()))
        except (OSError,ValueError,TypeError):
            self.config={'enabled':False,'client_path':''}

    @staticmethod
    def validate(value):
        if not isinstance(value,dict) or set(value)!={'enabled','client_path'} or type(value['enabled']) is not bool or not isinstance(value['client_path'], str):
            raise ValueError('Send enabled and client_path settings.')
        if value['client_path']:
            client_path(value['client_path'])
        elif value['enabled']:
            raise ValueError('Choose a client folder before enabling 3D.')
        return {'enabled':value['enabled'],'client_path':value['client_path'].strip()}

    def get_config(self):
        with self.lock:return dict(self.config)

    def save(self,value):
        checked=self.validate(value)
        with self.lock:
            target=self.root/'client-models.json';temporary=target.with_suffix('.tmp')
            temporary.write_text(json.dumps(checked)+'\n');temporary.chmod(0o600);temporary.replace(target)
            self.config=checked;self.results={}
        return checked

    @staticmethod
    def equipment(value):
        if not isinstance(value,list) or len(value)>19:raise ValueError('Invalid equipped items')
        slots=set();result=[]
        for item in value:
            if not isinstance(item,dict) or set(item)!={'slot','displayid','inventory_type'}:
                raise ValueError('Invalid equipped item')
            if any(type(v) is not int for v in item.values()):raise ValueError('Invalid equipped item')
            if not 0<=item['slot']<=18 or item['slot'] in slots or not 0<item['displayid']<=1000000 or not 0<=item['inventory_type']<=28:
                raise ValueError('Invalid equipped item')
            slots.add(item['slot']);result.append(dict(item))
        return sorted(result,key=lambda item:item['slot'])

    def get(self,character,equipment=None,weapon_mode='melee'):
        if set(character)!=set(APPEARANCE) or any(type(v) is not int or not 0<=v<=255 for v in character.values()):
            raise ValueError('Invalid saved appearance')
        if character['race'] not in RACES or character['gender'] not in (0,1):
            return {'available':False,'pending':False}
        equipment=self.equipment([] if equipment is None else equipment)
        if weapon_mode not in ('melee','ranged'):raise ValueError('Invalid weapon view')
        character={**character,'equipment':equipment,'weapon_mode':weapon_mode}
        with self.lock:
            config=dict(self.config)
            if not config['enabled']:return {'available':False,'pending':False}
            key=hashlib.sha256(json.dumps([config,character,3],sort_keys=True).encode()).hexdigest()
            if key in self.results:return self.results[key]
            if self.active:return {'available':False,'pending':True}
            self.active=key
            threading.Thread(target=self.prepare,args=(key,config,character),daemon=True).start()
            return {'available':False,'pending':True}

    def prepare(self,key,config,character):
        result={'available':False,'pending':False}
        try:
            # Availability is checked even with a cache: an unavailable configured client falls back normally.
            path=client_path(config['client_path'])
            if not (path/'Data').is_dir():raise ValueError('Client unavailable')
            target=self.root/'assets'/'models'/(key+'.json')
            if target.is_file():model=json.loads(target.read_text())
            else:
                model=self.builder(path,character)
                target.parent.mkdir(parents=True,exist_ok=True)
                temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(model));temporary.replace(target)
            result={'available':True,'pending':False,'model':model}
        except Exception:
            # The preview is optional. Never expose filesystem errors, paths or partial assets to the browser.
            pass
        finally:
            with self.lock:
                if config==self.config:
                    if len(self.results)>=32:self.results.pop(next(iter(self.results)))
                    self.results[key]=result
                if self.active==key:self.active=None
