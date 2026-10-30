"""Trainer progression is independent of installed addons and never writes game data."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
import dashboard
from mysql_access import DatabaseError
from training import TrainingProvider,training_records,training_sql,level_bounds


def spell(entry,name,**extra):
    return {'id':entry,'name':name,'rank':'','icon':None,'description':'Effect of '+name,'effects':[0,0,0],'triggers':[0,0,0],
            'cast':1,'range':1,'attributes':0,'power_type':1,'cost':150,'recovery':0,**extra}

def offer(entry,level,**extra):return {'class':1,'spell':entry,'level':level,'cost':100,'skill':0,'skill_rank':0,'abilities':[0,0,0],**extra}
META={'format':1,'casts':{'1':0},'ranges':{'1':[5,5]},'spells':{
    '78':spell(78,'Heroic Strike',rank='Rank 1'),'284':spell(284,'Heroic Strike',rank='Rank 2'),
    '285':spell(285,'Heroic Strike',rank='Rank 3'),'1160':spell(1160,'Demoralizing Shout',rank='Rank 1'),
    '6572':spell(6572,'Revenge',rank='Rank 1'),'674':spell(674,'Dual Wield',attributes=64),
    '333':spell(333,'Talent only'),'444':spell(444,'Quest only'),'555':spell(555,'Other class'),
    '777':spell(777,'Other race'),'600':spell(600,'Skill gated'),'601':spell(601,'Talent gated'),
    '9001':spell(9001,'Teach stance',effects=[36,0,0],triggers=[9002,0,0]),'9002':spell(9002,'Defensive Stance')},
    'training':{'offers':[offer(78,1),offer(284,8,abilities=[78,0,0]),offer(285,16,abilities=[284,0,0],cost=1000),
                          offer(285,16,abilities=[284,0,0],cost=2000),offer(1160,14),offer(6572,14),offer(674,20),
                          offer(333,10),offer(555,10,**{'class':8}),offer(777,20),offer(9001,10),
                          offer(600,10,skill=164,skill_rank=100),offer(601,10,abilities=[333,0,0])],
                'ranks':[{'id':78,'first':78,'rank':1},{'id':284,'first':78,'rank':2},{'id':285,'first':78,'rank':3}],
                'requirements':[],'talents':[333],
                'abilities':[{'id':1,'spell':1160,'skill':26,'race':1,'class':1},{'id':2,'spell':777,'skill':26,'race':2,'class':1}],
                'skill_rules':[{'id':1,'skill':26,'race':0,'class':1}]}}
ROWS=[{'kind':'character','guid':1,'name':'Aster','class':1,'race':1,'level':12},
      {'kind':'known','id':78},{'kind':'known','id':284},{'kind':'known','id':9002},
      {'kind':'skill','id':164,'value':50}]


class TrainingTests(unittest.TestCase):
    def test_screenshot_grouping_and_rank_tooltips(self):
        result=training_records(ROWS,META);rows={r['id']:r for r in result['abilities']}
        self.assertEqual(rows[1160]['state'],'soon');self.assertEqual(rows[6572]['required_level'],14)
        self.assertEqual(rows[285]['state'],'later');self.assertEqual(rows[285]['rank'],'Rank 3')
        self.assertEqual(rows[285]['base_cost'],1000)
        self.assertEqual(rows[674]['passive'],True);self.assertEqual(rows[1160]['power_cost'],'15 Rage')
        self.assertEqual(rows[1160]['cast_time_ms'],0);self.assertIn('Demoralizing Shout',rows[1160]['description'])

    def test_wrong_class_race_talents_and_quest_only_are_not_level_rewards(self):
        ids={r['id'] for r in training_records(ROWS,META)['abilities']}
        self.assertFalse(ids&{333,444,555,777,9001});self.assertIn(9002,ids)
        metadata=copy.deepcopy(META);metadata['training']['skill_rules']=[]
        self.assertNotIn(1160,{r['id'] for r in training_records(ROWS,metadata)['abilities']})

    def test_learn_wrapper_and_higher_rank_hide_obsolete_training(self):
        rows={r['id']:r for r in training_records(ROWS,META)['abilities']}
        self.assertEqual(rows[9002]['state'],'known')
        result=training_records([r for r in ROWS if r.get('id') not in (78,284)]+[{'kind':'known','id':285}],META)
        for row in result['abilities']:
            if row['id'] in (78,284,285):self.assertEqual(row['state'],'known')

    def test_prerequisites_and_skills_are_not_called_available(self):
        rows={r['id']:r for r in training_records(ROWS,META)['abilities']}
        self.assertEqual(rows[600]['state'],'blocked');self.assertIn('saved 50',rows[600]['requirements'][0])
        self.assertEqual(rows[601]['state'],'blocked');self.assertIn('Talent only',rows[601]['requirements'][0])
        metadata=copy.deepcopy(META);metadata['training']['requirements']=[{'id':1160,'required':333}]
        higher=[{**r,'level':14} if r['kind']=='character' else r for r in ROWS]
        rows={r['id']:r for r in training_records(higher,metadata)['abilities']}
        self.assertEqual(rows[1160]['state'],'blocked');self.assertEqual(rows[6572]['state'],'available')

    def test_character_dependent_formulas_keep_readable_context_without_guessed_values(self):
        metadata=copy.deepcopy(META)
        metadata['spells']['6572'].update(description='Counterattack for ${$m1+$AP*0.31} damage after a block.',base=[19,0,0],die=[1,0,0])
        row=next(r for r in training_records(ROWS,metadata)['abilities'] if r['id']==6572)
        self.assertIn('after a block',row['description'])
        self.assertIn('[depends on current stats]',row['description'])
        self.assertNotIn('$',row['description']);self.assertFalse(row['description_complete'])

    def test_missing_metadata_is_reported_and_wrappers_can_teach_multiple_spells(self):
        metadata=copy.deepcopy(META);metadata['training']['offers'].append(offer(999,10))
        self.assertEqual(training_records(ROWS,metadata)['skipped'],1)
        metadata['spells']['9001']['effects']=[36,36,0];metadata['spells']['9001']['triggers']=[9002,674,0]
        metadata['training']['offers']=[offer(9001,20)]
        rows={r['id']:r for r in training_records(ROWS,metadata)['abilities']}
        self.assertEqual(set(rows),{9002,674});self.assertEqual(rows[9002]['state'],'known')
        self.assertEqual(rows[674]['state'],'later')

    def test_limits_missing_character_and_no_partial_data(self):
        with self.assertRaises(LookupError):training_records([],META)
        with self.assertRaises(DatabaseError):training_records(ROWS+[ROWS[0]],META)
        with self.assertRaises(DatabaseError):training_records([ROWS[0]]+[{'kind':'known','id':1}]*20001,META)
        with self.assertRaises(DatabaseError):training_records([ROWS[0]]+[{'kind':'skill','id':1,'value':1}]*2001,META)

    def test_numeric_level_filter_and_safe_sql(self):
        self.assertEqual(level_bounds('14'),(14,14));self.assertEqual(level_bounds('14–20'),(14,20))
        self.assertEqual(level_bounds(''),(1,255))
        for value in ('0','256','20-14','14 OR 1','abc','1.5',None):
            with self.assertRaises(ValueError):level_bounds(value)
        sql=training_sql('Aster')
        for value in ['CONSISTENT SNAPSHOT, READ ONLY','MAX_EXECUTION_TIME=3000','0x4173746572','LIMIT 20001','LIMIT 2001','COMMIT;']:self.assertIn(value,sql)
        self.assertNotIn('WTF',sql)
        for name in ('Aster;DROP','A','',None):
            with self.assertRaises(ValueError):training_sql(name)

    def test_provider_filters_and_cache_are_scoped_to_character(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'assets').mkdir();(root/'assets/tooltip-metadata.json').write_text(json.dumps(META))
            reader=Mock(return_value=ROWS);provider=TrainingProvider(root,reader)
            result=provider.get('Aster');self.assertEqual({r['id'] for r in result['abilities']},{285,1160,6572,674})
            self.assertEqual([r['id'] for r in provider.get('Aster',search='heroic rank 3',level='14-20')['abilities']],[285])
            self.assertEqual({r['id'] for r in provider.get('Aster',level='14')['abilities']},{1160,6572})
            self.assertEqual(len(reader.call_args_list),1)
            self.assertFalse(provider.get('Aster',mode='available')['abilities'])
            self.assertIn(600,{r['id'] for r in provider.get('Aster',mode='unlearned')['abilities']})
            self.assertIn(78,{r['id'] for r in provider.get('Aster',mode='all')['abilities']})
            provider.get('Bran');self.assertEqual(reader.call_count,2)
            with self.assertRaises(ValueError):provider.get('Aster',mode='bad')
            with self.assertRaises(DatabaseError):TrainingProvider(Path(folder)/'fresh',reader).get('Aster')

    def test_http_page_assets_validation_and_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'assets').mkdir();(root/'assets/tooltip-metadata.json').write_text(json.dumps(META))
            provider=TrainingProvider(root,lambda sql:ROWS if '0x4173746572' in sql else [])
            with patch('dashboard.TrainingProvider',return_value=provider):
                cache=dashboard.SnapshotCache(reader=lambda names:[]);server=ThreadingHTTPServer(('127.0.0.1',0),dashboard.handler(cache,0));server.RequestHandlerClass=dashboard.handler(cache,server.server_port)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            try:
                base=f'http://127.0.0.1:{server.server_port}'
                result=json.load(urlopen(base+'/api/training?name=Aster&level=14'));self.assertEqual(len(result['result']['abilities']),2)
                for path in ['/training','/training.js','/training.css']:self.assertEqual(urlopen(base+path).status,200)
                html=urlopen(base+'/training').read().decode();self.assertIn('What’s Training',html)
                for path,code in [('/api/training',400),('/api/training?name=Aster&name=Bran',400),('/api/training?name=Aster&level=0',400),('/api/training?name=Aster&other=1',400),('/api/training?name=Missing',404)]:
                    with self.assertRaises(HTTPError) as error:urlopen(base+path)
                    self.assertEqual(error.exception.code,code)
            finally:server.shutdown();server.server_close()
