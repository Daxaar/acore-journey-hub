import json
from pathlib import Path
import tempfile
import unittest
from bot_monitor import BotMonitor

class MonitorTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)
  self.monitor=BotMonitor(self.path,classes={1:'Warrior'},clock=lambda:100000)
  self.monitor.update({'enabled':True,'interval_ms':5000,'include_quests':True})
  self.rows=[dict(guid=i,name=name,level=15,bot_type=kind,**{'class':1},race=1,faction='Alliance',map_id=0,zone_id=40,zone_name='Westfall',map_name='Eastern Kingdoms',area_name='Moonbrook') for i,name,kind in [(1,'Human','human'),(2,'Alt','alt_bot'),(3,'Random','random_bot')]]
 def snapshot(self,**extra):
  data=dict(schema_version=1,characters=self.rows,enabled=True,generated_at_ms=99000,interval_ms=5000);data.update(extra);(self.path/'snapshot.json').write_text(json.dumps(data))
 def test_overview_does_not_send_characters(self):
  self.snapshot();result=self.monitor.get({});self.assertEqual(result['counts']['total'],3);self.assertEqual(result['characters'],[]);self.assertEqual(result['zones'][0]['bots'],2)
 def test_zone_filter_and_class_names(self):
  self.snapshot();result=self.monitor.get({'map':['0'],'zone':['40'],'type':['alt_bot']});self.assertEqual([r['name'] for r in result['characters']],['Alt']);self.assertEqual(result['characters'][0]['class_name'],'Warrior')
 def test_stale_never_claims_online_counts(self):
  self.snapshot(generated_at_ms=1000);result=self.monitor.get({});self.assertEqual(result['state'],'stale');self.assertIsNone(result['counts']);self.assertEqual(result['characters'],[])
 def test_off_hides_previous_snapshot(self):
  self.snapshot();self.monitor.update({'enabled':False,'interval_ms':5000,'include_quests':False});self.assertEqual(self.monitor.get({})['state'],'off');self.assertIsNone(self.monitor.get({})['counts'])
 def test_invalid_controls_do_not_overwrite(self):
  before=(self.path/'control.txt').read_bytes()
  for payload in [{'enabled':1,'interval_ms':5000,'include_quests':True},{'enabled':True,'interval_ms':1,'include_quests':True}]:
   with self.assertRaises(ValueError):self.monitor.update(payload)
  self.assertEqual(before,(self.path/'control.txt').read_bytes())
 def test_atomic_snapshot_replacement_invalidates_cache(self):
  self.snapshot();self.assertEqual(self.monitor.get({})['counts']['total'],3);replacement=self.path/'next';data=json.loads((self.path/'snapshot.json').read_text());data['characters']=[];replacement.write_text(json.dumps(data));replacement.replace(self.path/'snapshot.json');self.assertEqual(self.monitor.get({})['counts']['total'],0)
 def test_filter_validation(self):
  for params in [{'map':['0']},{'type':['typo']},{'q':['one','two']},{'min':['50'],'max':['2']}]:
   with self.assertRaises(ValueError):self.monitor.get(params)
if __name__=='__main__':unittest.main()
