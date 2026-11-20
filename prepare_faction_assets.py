#!/usr/bin/env python3
"""Read authentic faction emblems from a local WotLK client; never modify client files."""
import argparse
from pathlib import Path
import struct
import zlib
from client_models import Archives,blp,client_path

def prepare(client,output):
 output=Path(output);output.mkdir(parents=True,exist_ok=True)
 archives=Archives(client_path(str(client)))
 def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
 try:
  for faction in ('Alliance','Horde'):
   source='Interface\\TargetingFrame\\UI-PVP-'+faction+'.blp'
   width,height,rgba=blp(archives.read(source))
   rows=b''.join(b'\0'+rgba[y*width*4:(y+1)*width*4] for y in range(height))
   png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')
   (output/('faction-'+faction.lower()+'.png')).write_bytes(png)
   print(faction,source,width,height)
 finally:archives.close()
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('client');parser.add_argument('--output',default=str(Path(__file__).parent/'static'));args=parser.parse_args();prepare(args.client,args.output)
