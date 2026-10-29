"""Lightweight carried-bag summaries and read-only API boundaries."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from armory import ArmoryProvider, bag_space_sql
from mysql_access import DatabaseError


class BagSpaceTests(unittest.TestCase):
    def test_zero_free_is_distinct_from_missing_and_order_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            p=ArmoryProvider(Path(directory))
            reader=lambda sql:[{'kind':'space','name':'Bran','capacity':24,'occupied':7},
                               {'kind':'space','name':'Aster','capacity':16,'occupied':16}]
            result=p.bag_space(['Aster','Missing','Bran'],reader)
            self.assertEqual([r['free'] for r in result['characters']],[0,None,17])
            self.assertEqual([r['found'] for r in result['characters']],[True,False,True])

    def test_query_uses_equipped_bag_guids_and_excludes_bank_and_storage(self):
        sql=bag_space_sql(['Aster','Bran'])
        for clause in ['bv.slot BETWEEN 19 AND 22','v.slot BETWEEN 23 AND 38',
                       'b.item=v.bag','v.slot<bt.ContainerSlots','bt.ContainerSlots BETWEEN 0 AND 64',
                       'COUNT(DISTINCT','LIMIT 6','MAX_EXECUTION_TIME=3000','CONSISTENT SNAPSHOT, READ ONLY','COMMIT;']:
            self.assertIn(clause,sql)
        self.assertNotIn('guild_bank',sql)
        self.assertIn('0x4173746572',sql)
        for names in [[],['Aster']*7,['../Aster'],["Aster'; DROP TABLE x"],None]:
            with self.assertRaises(ValueError):bag_space_sql(names)

    def test_failed_summary_is_not_cached_as_zero_or_substituted_for_other_group(self):
        with tempfile.TemporaryDirectory() as directory:
            p=ArmoryProvider(Path(directory))
            reader=lambda sql:[{'kind':'space','name':'Aster','capacity':16,'occupied':2}]
            p.bag_space(['Aster'],reader)
            with self.assertRaises(DatabaseError):
                p.bag_space(['Bran'],lambda sql:(_ for _ in ()).throw(DatabaseError('QA outage')))
            self.assertEqual(len(p.space_cached),1)
            missing=p.bag_space(['Bran'],lambda sql:[])['characters'][0]
            self.assertIsNone(missing['free'])

    def test_summary_http_validates_name_list(self):
        import json,threading
        from http.server import ThreadingHTTPServer
        from urllib.request import urlopen
        from urllib.error import HTTPError
        import dashboard
        with patch.object(ArmoryProvider,'bag_space',return_value={'characters':[{'name':'Aster','free':4,'found':True}]}):
            server=ThreadingHTTPServer(('127.0.0.1',0),dashboard.handler(fixture_cache(reader=lambda names:[]),0))
            server.RequestHandlerClass=dashboard.handler(fixture_cache(reader=lambda names:[]),server.server_port)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                result=json.load(urlopen(base+'/api/armory/space?names=Aster'))
                self.assertEqual(result['space']['characters'][0]['free'],4)
                for path in ['?names=Aster&names=Bran','?extra=1']:
                    with self.assertRaises(HTTPError) as error:urlopen(base+'/api/armory/space'+path)
                    self.assertEqual(error.exception.code,400)
            finally:
                server.shutdown();server.server_close();thread.join()


from test_support import fixture_cache

if __name__=='__main__':unittest.main()
