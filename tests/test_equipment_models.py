"""Equipment cache validity, clothing layers, pose transforms and hostile-input bounds."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from client_models import ClientModels, overlay
from equipment_models import clothing, pose_matrices, posed_vertices


class EquippedModelTests(unittest.TestCase):
    def test_equipment_validation_rejects_duplicate_slots_and_invalid_values(self):
        valid={'slot':15,'displayid':26591,'inventory_type':17}
        self.assertEqual(ClientModels.equipment([valid]),[valid])
        for value in [None,{},[valid,valid],[{**valid,'slot':19}],[{**valid,'displayid':0}],
                      [{**valid,'inventory_type':29}],[{**valid,'slot':True}],
                      [{**valid,'displayid':'26591'}],[{**valid,'extra':'/etc/passwd'}]]:
            with self.subTest(value=value),self.assertRaises(ValueError):ClientModels.equipment(value)

    def test_cache_changes_when_gear_or_weapon_view_changes(self):
        appearance={'race':7,'gender':1,'skin':2,'face':1,'hairStyle':2,'hairColor':7,'facialStyle':1}
        calls=[]
        def builder(root,request):
            calls.append(request)
            return {'equipment':request['equipment'],'mode':request['weapon_mode']}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'Data').mkdir()
            provider=ClientModels(root,builder)
            provider.save({'enabled':True,'client_path':directory})
            def ready(gear,mode='melee'):
                for _ in range(200):
                    result=provider.get(appearance,gear,mode)
                    if not result['pending']:return result
                    time.sleep(.01)
                self.fail('Optional model worker did not finish')
            sword={'slot':15,'displayid':26591,'inventory_type':17}
            chest={'slot':4,'displayid':26936,'inventory_type':5}
            first=ready([sword,chest]);self.assertTrue(first['available'])
            self.assertEqual(ready([chest,sword]),first);self.assertEqual(len(calls),1)
            changed=ready([chest]);self.assertNotEqual(first['model'],changed['model']);self.assertEqual(len(calls),2)
            ranged=ready([chest],'ranged');self.assertEqual(ranged['model']['mode'],'ranged');self.assertEqual(len(calls),3)
            self.assertEqual(len(list((root/'assets'/'models').glob('*.json'))),3)
            with self.assertRaises(ValueError):provider.get(appearance,[],weapon_mode='invalid')

    def test_clothing_layers_keep_chest_over_shirt_and_gloves_over_bracers(self):
        records={}
        for slot,label in [(3,'shirt'),(4,'chest'),(8,'bracers'),(9,'gloves'),(7,'boots')]:
            row=[0]*25;row[18 if slot in (3,4) else 16]=slot
            records[slot]=({'inventory_type':5},row)
        names={3:'shirt',4:'chest',8:'bracers',9:'gloves',7:'boots'}
        paths=[]
        class Archive:
            def read(self,path):paths.append(path);return path.encode()
        selected={0,401,502,801,1001,1301}
        with patch('equipment_models.blp',side_effect=lambda data:data),patch('equipment_models.overlay') as compose:
            clothing(Archive(),records,lambda i:names.get(i,''),None,selected,1)
        layers=[call.args[1].decode() for call in compose.call_args_list]
        self.assertLess(next(i for i,p in enumerate(layers) if 'shirt' in p),next(i for i,p in enumerate(layers) if 'chest' in p))
        self.assertLess(next(i for i,p in enumerate(layers) if 'bracers' in p),next(i for i,p in enumerate(layers) if 'gloves' in p))
        self.assertTrue(all(p.endswith('_F.blp') for p in paths))
        self.assertIn(502,selected)
        self.assertNotIn(501,selected)

    def test_robe_hides_pants_boot_and_tabard_geosets(self):
        row=[0]*25
        selected={0,501,901,1101,1201,1301}
        clothing(None,{4:({'inventory_type':20},row)},lambda i:'',None,selected,0)
        self.assertIn(1302,selected)
        self.assertFalse(any(i//100 in (5,9,11,12) for i in selected))

    def test_texture_layer_changes_only_its_atlas_region(self):
        pixels=bytearray(bytes((0,0,255,255))*256*256)
        overlay((256,256,pixels),(1,1,bytes((255,0,0,128))),(128,0,128,64))
        self.assertEqual(bytes(pixels[:4]),bytes((0,0,255,255)))
        self.assertEqual(bytes(pixels[128*4:128*4+4]),bytes((128,0,127,255)))
        self.assertEqual(bytes(pixels[(64*256+128)*4:(64*256+128)*4+4]),bytes((0,0,255,255)))

    def pose(self,cycle=False):
        data=bytearray(1024)
        struct.pack_into('<II',data,28,1,128);struct.pack_into('<H',data,128,0);struct.pack_into('<I',data,140,32)
        struct.pack_into('<II',data,44,2,256)
        empty=struct.pack('<Hh4I',0,-1,0,0,0,0)
        for i,(parent,translation) in enumerate([((1 if cycle else -1),(1,0,0)),(0,(0,2,0))]):
            headers=600+i*48;values=headers+16
            track=struct.pack('<Hh4I',0,-1,0,0,1,headers)
            struct.pack_into('<II',data,headers,1,values);struct.pack_into('<3f',data,values,*translation)
            struct.pack_into('<iIhHI20s20s20s3f',data,256+i*88,-1,512,parent,0,0,track,empty,empty,0,0,0)
        return data

    def test_standing_pose_composes_parent_and_child_before_vertex_skinning(self):
        matrices=pose_matrices(self.pose())
        raw=[(0.,0.,0.,255,0,0,0,1,0,0,0,0.,0.,1.,.25,.5,0.,0.)]
        result=posed_vertices(raw,matrices)
        self.assertEqual(result[0][:3],[1.,2.,0.])
        self.assertEqual(result[0][3:],[0.,0.,1.,.25,.5])
        with self.assertRaises(ValueError):pose_matrices(self.pose(cycle=True))


if __name__=='__main__':unittest.main()
