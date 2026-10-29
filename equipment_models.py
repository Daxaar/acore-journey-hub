"""Local WotLK clothing atlas, geosets, standing-pose skinning and rigid item attachments."""
import math
import struct
from client_models import array, dbc, blp, overlay

IDENTITY=(1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.)
REGIONS=(('ArmUpperTexture',(0,0,128,64)),('ArmLowerTexture',(0,64,128,64)),
         ('HandTexture',(0,128,128,32)),('TorsoUpperTexture',(128,0,128,64)),
         ('TorsoLowerTexture',(128,64,128,32)),('LegUpperTexture',(128,96,128,64)),
         ('LegLowerTexture',(128,160,128,64)),('FootTexture',(128,224,128,32)))
# Layer by garment, with chest over shirt and gloves over bracers.
LAYER_ORDER=(3,6,7,4,18,5,8,9)
RACE_CODES={1:'Hu',2:'Or',3:'Dw',4:'Ni',5:'Sc',6:'Ta',7:'Gn',8:'Tr',10:'Be',11:'Dr'}


def multiply(a,b):
    return tuple(sum(a[r*4+k]*b[k*4+c] for k in range(4)) for r in range(4) for c in range(4))


def vector(matrix,value,point=True):
    return tuple(sum(matrix[r*4+c]*value[c] for c in range(3))+(matrix[r*4+3] if point else 0) for r in range(3))


def translation(value):
    result=list(IDENTITY)
    for r in range(3):result[r*4+3]=value[r]
    return tuple(result)


def pose_matrices(model):
    count,address=struct.unpack_from('<II',model,28)
    if count>1000 or address+count*64>len(model):raise ValueError('Invalid pose table')
    sequence=next((i for i in range(count) if struct.unpack_from('<H',model,address+i*64)[0]==0),None)
    if sequence is None or not struct.unpack_from('<I',model,address+sequence*64+12)[0]&32:
        raise ValueError('Embedded standing pose unavailable')
    bones=array(model,44,'iIhHI20s20s20s3f',512)
    def key(track,fmt,default):
        _,global_sequence,_,_,n,offset=struct.unpack('<Hh4I',track)
        if not n:return default
        if n>1000 or offset+n*8>len(model):raise ValueError('Invalid pose track')
        index=0 if global_sequence>=0 else sequence
        if index>=n:return default
        size=struct.calcsize('<'+fmt)
        count,offset=struct.unpack_from('<II',model,offset+index*8)
        if not count:return default
        if count>100000 or offset+size>len(model):raise ValueError('Unsupported pose data')
        value=struct.unpack_from('<'+fmt,model,offset)
        if not all(math.isfinite(v) for v in value):raise ValueError('Invalid pose value')
        return value
    matrices={};visiting=set()
    def bone(index):
        if index in matrices:return matrices[index]
        if index in visiting or not 0<=index<len(bones):raise ValueError('Invalid bone hierarchy')
        visiting.add(index);row=bones[index]
        parent=row[2];pivot=row[-3:]
        move=key(row[5],'3f',(0,0,0));scale=key(row[7],'3f',(1,1,1))
        q=key(row[6],'4h',None)
        x,y,z,w=(0,0,0,1) if q is None else tuple((v+32768 if v<0 else v-32767)/32767 for v in q)
        length=math.sqrt(x*x+y*y+z*z+w*w)
        if not length:raise ValueError('Invalid bone rotation')
        x,y,z,w=x/length,y/length,z/length,w/length
        rotation=(1-2*y*y-2*z*z,2*x*y-2*z*w,2*x*z+2*y*w,0,
                  2*x*y+2*z*w,1-2*x*x-2*z*z,2*y*z-2*x*w,0,
                  2*x*z-2*y*w,2*y*z+2*x*w,1-2*x*x-2*y*y,0,0,0,0,1)
        scaled=tuple(rotation[r*4+c]*(scale[c] if c<3 else 1) for r in range(4) for c in range(4))
        local=multiply(translation(tuple(pivot[i]+move[i] for i in range(3))),multiply(scaled,translation(tuple(-v for v in pivot))))
        result=multiply(bone(parent),local) if parent>=0 else local
        if not all(math.isfinite(v) for v in result):raise ValueError('Invalid bone transform')
        matrices[index]=result;visiting.remove(index);return result
    for i in range(len(bones)):bone(i)
    return matrices


def posed_vertices(vertices,matrices):
    result=[]
    for row in vertices:
        position=[0.,0.,0.];normal=[0.,0.,0.];total=sum(row[3:7])
        if not total:
            result.append(list(row[:3]+row[11:16]));continue
        for weight,index in zip(row[3:7],row[7:11]):
            if not weight:continue
            matrix=matrices[index];point=vector(matrix,row[:3]);direction=vector(matrix,row[11:14],False)
            for i in range(3):position[i]+=point[i]*weight/total;normal[i]+=direction[i]*weight/total
        norm=math.sqrt(sum(v*v for v in normal)) or 1
        result.append(position+[v/norm for v in normal]+list(row[14:16]))
    return result


def item_rows(archives,equipment):
    rows,string=dbc(archives.read('DBFilesClient\\ItemDisplayInfo.dbc'),25)
    wanted={item['displayid'] for item in equipment}
    records={row[0]:row for row in rows if row[0] in wanted}
    if wanted-set(records):raise ValueError('Equipped display unavailable')
    return {item['slot']:(item,records[item['displayid']]) for item in equipment},string


def clothing(archives,items,string,texture,selected,gender):
    for slot in LAYER_ORDER:
        if slot not in items:continue
        _,row=items[slot]
        for i,(directory,region) in enumerate(REGIONS):
            stem=string(row[15+i])
            if not stem:continue
            if '\\' in stem or '/' in stem or '..' in stem:raise ValueError('Unsupported clothing path')
            loaded=None
            for suffix in (('_F' if gender else '_M'),'_U',''):
                try:loaded=archives.read('Item\\TextureComponents\\'+directory+'\\'+stem+suffix+'.blp');break
                except ValueError:continue
            if loaded is None:raise ValueError('Equipped clothing texture unavailable')
            overlay(texture,blp(loaded),region)
    def geoset(group,value):
        selected.difference_update(i for i in tuple(selected) if i//100==group)
        if value:selected.add(group*100+value)
    for slot,groups in [(6,((11,7),(9,8),(13,9))),(3,((8,7),(10,8),(13,9))),
                        (4,((8,7),(10,8),(13,9))),(7,((5,7),)),(9,((4,7),)),(18,((12,7),))]:
        if slot in items:
            row=items[slot][1]
            for group,field in groups:geoset(group,2 if group==5 and row[field]==0 else 1+row[field])
    # Ordinary bare feet use geoset 2 on races that supply boot alternatives.
    if 7 not in items:geoset(5,2)
    if 14 in items:geoset(15,1+items[14][1][7])
    if 4 in items and items[4][0]['inventory_type']==20:
        geoset(13,2);geoset(5,0);geoset(9,0);geoset(11,0);geoset(12,0)
    if 9 in items and items[9][1][7]:geoset(8,0)
    return texture,selected


def component(archives,path,replacement):
    model=archives.read(path);skin=archives.read(path[:-3]+'00.skin')
    if model[:4]!=b'MD20' or struct.unpack_from('<I',model,4)[0]!=264 or skin[:4]!=b'SKIN':
        raise ValueError('Unsupported equipped component')
    raw=array(model,60,'3f4B4B3f2f2f',60000)
    vertices=[list(v[:3]+v[11:16]) for v in raw]
    if not all(all(math.isfinite(x) for x in v) for v in vertices):raise ValueError('Invalid component coordinates')
    lookup=[r[0] for r in array(skin,4,'H',65535)]
    triangles=[r[0] for r in array(skin,12,'H',300000)]
    indices=[]
    for index in triangles:
        if index>=len(lookup) or lookup[index]>=len(vertices):raise ValueError('Invalid equipment geometry')
        indices.append(lookup[index])
    if len(indices)%3:raise ValueError('Invalid equipment triangles')
    meshes=array(skin,28,'10H7f',500)
    units=array(skin,36,'Bb11H',2000)
    textures=array(model,80,'4I',100)
    texture_lookup=[r[0] for r in array(model,128,'H',500)]
    material_flags=array(model,112,'2H',500)
    loaded=[];texture_indices={};groups=[]
    for mesh_index,mesh in enumerate(meshes):
        # Select a base material rather than duplicating additive glow/reflection passes.
        batches=[u for u in units if u[3]==mesh_index]
        if not batches:raise ValueError('Missing equipment material')
        batch=next((u for u in batches if u[6]<len(material_flags) and material_flags[u[6]][1] in (0,1,2)),batches[0])
        if batch[9]>=len(texture_lookup):raise ValueError('Invalid material lookup')
        ti=texture_lookup[batch[9]]
        if ti>=len(textures):raise ValueError('Invalid equipment texture')
        texture=textures[ti]
        if texture[0]==0:
            length,offset=texture[2:]
            if length>500 or offset+length>len(model):raise ValueError('Invalid embedded texture path')
            texture_path=model[offset:offset+length].split(b'\0')[0].decode('utf-8')
        elif texture[0]==2 and replacement:texture_path=replacement
        else:raise ValueError('Unsupported equipment material')
        if texture_path not in texture_indices:
            texture_indices[texture_path]=len(loaded);loaded.append(blp(archives.read(texture_path)))
        start=(mesh[1]<<16)+mesh[4];count=mesh[5]
        if start+count>len(indices) or count%3:raise ValueError('Invalid equipment draw range')
        groups.append({'start':start,'count':count,'texture':texture_indices[texture_path]})
    return vertices,indices,groups,loaded


def attachments(archives,model,items,string,matrices,character):
    points={row[0]:row for row in array(model,240,'IHH3f20s',100)}
    specifications=[]
    for slot,directory,channels in [(0,'Head',((1,3,11),)),(2,'Shoulder',((1,3,6),(2,4,5))),
                                    (15,'Weapon',((1,3,1),)),(16,'Weapon',((1,3,2),))]:
        if slot not in items:continue
        item,row=items[slot]
        if slot==16 and item['inventory_type']==14:
            directory='Shield';channels=((1,3,0),)
        for model_field,texture_field,attachment in channels:
            filename=string(row[model_field])
            if not filename:continue
            stem=filename.rsplit('.',1)[0]
            if '\\' in stem or '/' in stem or '..' in stem:raise ValueError('Unsupported equipment filename')
            if slot==0:stem+='_'+RACE_CODES[character['race']]+('F' if character['gender'] else 'M')
            path='Item\\ObjectComponents\\'+directory+'\\'+stem+'.m2'
            replacement=string(row[texture_field])
            replacement='Item\\ObjectComponents\\'+directory+'\\'+replacement+'.blp' if replacement else None
            if attachment not in points:raise ValueError('Missing character attachment')
            point=points[attachment];matrix=matrices[point[1]]
            transform=multiply(matrix,translation(point[3:6]))
            specifications.append((item['slot'],path,replacement,transform))
    result=[]
    for slot,path,replacement,transform in specifications:
        vertices,indices,groups,textures=component(archives,path,replacement)
        for vertex in vertices:
            vertex[:3]=vector(transform,vertex[:3]);normal=vector(transform,vertex[3:6],False)
            size=math.sqrt(sum(x*x for x in normal)) or 1;vertex[3:6]=[x/size for x in normal]
        result.append((slot,vertices,indices,groups,textures))
    return result


def apply_equipment(archives,model,skin,raw,character,texture,selected,hair_geo):
    equipment=character.get('equipment',[])
    items,string=item_rows(archives,equipment)
    texture,selected=clothing(archives,items,string,texture,selected,character['gender'])
    if 0 in items and items[0][1][1]:
        # Basic helmet visibility: avoid hair/ears protruding through rigid head components.
        selected.difference_update(i for i in tuple(selected) if i<100 and i!=0 or i//100 in (1,2,3,7))
        hair_geo=None
    matrices=pose_matrices(model)
    vertices=posed_vertices(raw,matrices)
    weapons=dict(items)
    if character.get('weapon_mode')=='ranged':
        weapons.pop(15,None);weapons.pop(16,None)
        if 17 in items:weapons[15]=items[17]
    attached=attachments(archives,model,weapons,string,matrices,character)
    cape=blp(archives.read('Item\\ObjectComponents\\Cape\\'+string(items[14][1][3])+'.blp')) if 14 in items else None
    return vertices,texture,selected,hair_geo,cape,attached
