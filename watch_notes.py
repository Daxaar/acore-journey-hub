"""Dashboard-only character notes and one optional image; no game database writes."""
import base64
import json
from pathlib import Path
import re
import threading
from mysql_access import name_filter
from journal import screenshot

MAX_NOTE = 2000
MAX_NOTE_REQUEST = 7 * 1024 * 1024
KEEP_IMAGE = object()


def validate(name, text):
    if not isinstance(name,str):raise ValueError('Choose a character name using 2–12 letters.')
    name_filter('c',[name])
    if not isinstance(text,str) or len(text)>MAX_NOTE or any((ord(c)<32 and c not in '\n\r\t') or 0xD800<=ord(c)<=0xDFFF for c in text):
        raise ValueError('Write a note of up to 2,000 characters.')
    return name.capitalize(),text.strip()


def note_image(value, stored=False):
    expected = {'id','name','mime','data'} if stored else {'name','data'}
    if not isinstance(value,dict) or set(value)!=expected:
        raise ValueError('Attach one PNG or JPEG image.')
    result = screenshot(value)
    if stored:
        if not isinstance(value['id'],str) or not re.fullmatch('[a-f0-9]{32}',value['id']) or value['mime']!=result['mime']:
            raise ValueError('Invalid saved note image.')
        result['id']=value['id']
    return result


def image_info(image):
    return {key:image[key] for key in ('id','name','mime')} | {'url':'/watch-note-images/'+image['id']}


class WatchNotes:
    def __init__(self,path=None):
        self.path=Path(path) if path else None
        self.lock=threading.Lock();self.notes={};self.images={}
        if self.path and self.path.exists():
            data=json.loads(self.path.read_text())
            if not isinstance(data,dict):raise ValueError('watch-notes.json must contain character notes.')
            seen=set()
            for name,record in data.items():
                image=None
                if isinstance(record,dict):
                    if set(record)!={'text','image'}:raise ValueError('Invalid saved character note.')
                    image=note_image(record['image'],stored=True)
                    record=record['text']
                key,value=validate(name,record)
                if key in seen:raise ValueError('Duplicate character name in watch-notes.json.')
                seen.add(key)
                if value or image:self.notes[key]=value
                if image:self.images[key]=image

    def get(self):
        # Image bytes are served separately, never included in every session response.
        with self.lock:return dict(self.notes)

    def get_images(self):
        with self.lock:return {name:image_info(image) for name,image in self.images.items()}

    def image(self,reference):
        with self.lock:
            if isinstance(reference,str) and re.fullmatch('[a-f0-9]{32}',reference):
                for image in self.images.values():
                    if image['id']==reference:return image['mime'],image['data']
        raise LookupError('Note image not found.')

    def save(self,name,text,image=KEEP_IMAGE):
        key,value=validate(name,text)
        replacement=note_image(image) if image is not KEEP_IMAGE and image is not None else image
        with self.lock:
            updated=dict(self.notes);images=dict(self.images)
            if replacement is not KEEP_IMAGE:
                if replacement is None:images.pop(key,None)
                else:images[key]=replacement
            if value or key in images:updated[key]=value
            else:updated.pop(key,None)
            if self.path:
                records=dict(updated)
                for owner,picture in images.items():
                    records[owner]={'text':updated[owner],'image':{
                        **{field:picture[field] for field in ('id','name','mime')},
                        'data':base64.b64encode(picture['data']).decode('ascii')}}
                temporary=self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps(records,ensure_ascii=False)+'\n')
                temporary.chmod(0o600);temporary.replace(self.path)
            self.notes=updated;self.images=images
            result={'name':key,'text':value}
            if key in images:result['image']=image_info(images[key])
            elif image is not KEEP_IMAGE:result['image']=None
            return result
