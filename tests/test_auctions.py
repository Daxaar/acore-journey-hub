"""Auction filters, SQL boundaries, pagination and empty/error states."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from auctions import AuctionProvider, auction_sql, filters
from mysql_access import DatabaseError


class AuctionTests(unittest.TestCase):
    def test_untrusted_search_is_only_utf8_hex_and_wildcards_are_literal(self):
        term="x%' OR 1=1; DROP TABLE auctionhouse; --"
        sql=auction_sql({'q':[term]})
        self.assertNotIn(term,sql)
        self.assertIn(term.encode().hex(),sql)
        self.assertIn('LOCATE(',sql)
        self.assertIn('READ ONLY',sql)
        self.assertIn('CONSISTENT SNAPSHOT',sql)
        self.assertIn('a.time>UNIX_TIMESTAMP()',sql)
        self.assertIn('i.count>0',sql)
        self.assertIn('LIMIT 60 OFFSET 0',sql)

    def test_item_tooltip_stats_are_in_both_listing_and_detail_queries(self):
        for detail,params in [(False,{}),(True,{'id':['123']})]:
            sql=auction_sql(params,detail)
            for field in ('armor','block','dmg_min1','dmg_max1','delay','bonding','ContainerSlots','MaxDurability','stat_type1','stat_value1','stat_type10','stat_value10'):
                self.assertIn('MAX(t.'+field+') AS '+field,sql)
                self.assertIn("'"+field+"',g."+field,sql)

    def test_house_category_quality_level_and_sort_apply(self):
        sql=auction_sql({'house':['horde'],'category':['7'],'quality':['3'],'min':['10'],
                         'max':['80'],'sort':['price'],'page':['2']})
        for fragment in ['a.houseid IN (4,5,6)','t.class=7','t.Quality=3',
                         't.ItemLevel>=10','t.ItemLevel<=80','unit_price IS NULL, unit_price','OFFSET 60']:
            self.assertIn(fragment,sql)
        self.assertIn('THEN a.buyoutprice/i.count END',sql)

    def test_invalid_and_duplicate_parameters_rejected(self):
        for params in [{'house':['other']},{'q':['a','b']},{'sort':['DROP']},{'quality':['9']},
                       {'category':['8']},{'min':['60'],'max':['10']},{'page':['0']},
                       {'page':['10001']},{'q':['x'*101]},{'extra':['1']},{'q':['x\n']}]:
            with self.subTest(params=params),self.assertRaises(ValueError):filters(params)
        for params in [{'id':['0']},{'id':['1 OR 1=1']},{'id':['1'],'q':['x']}]:
            with self.subTest(params=params),self.assertRaises(ValueError):auction_sql(params,True)

    def test_hierarchical_subcategory_and_slot_filters_are_bounded(self):
        sql=auction_sql({'category':['4'],'subclass':['1'],'slot':['5,20'],'sort':['price_desc']})
        self.assertIn('t.class=4',sql)
        self.assertIn('t.subclass IN (1)',sql)
        self.assertIn('t.InventoryType IN (5,20)',sql)
        self.assertIn('unit_price IS NULL, unit_price DESC',sql)
        self.assertIn('MAX(t.RequiredSkillRank) AS skill_rank',sql)
        for params in [{'subclass':['1']},{'category':['4'],'subclass':['1);DROP']},
                       {'category':['4'],'slot':['29']},{'category':['2'],'subclass':['-1']},
                       {'category':['4'],'slot':['1,,3']},{'category':['4'],'subclass':['１']}]:
            with self.subTest(params=params),self.assertRaises(ValueError):filters(params)

    def test_detail_paginates_listings_and_limits_price_points(self):
        sql=auction_sql({'id':['123'],'house':['neutral'],'page':['3']},True)
        self.assertIn('i.itemEntry=123',sql)
        self.assertIn('a.houseid IN (7)',sql)
        self.assertIn('LIMIT 60 OFFSET 120',sql)
        self.assertIn('LIMIT 201',sql)
        self.assertIn("'random_property',i.randomPropertyId",sql)
        self.assertIn('a.buyoutprice=0,a.buyoutprice/i.count',sql)

    def test_empty_installation_and_cached_snapshot(self):
        reader=Mock(return_value=[{'kind':'totals','items':0,'auctions':0,'quantity':0}])
        with tempfile.TemporaryDirectory() as folder:
            provider=AuctionProvider(Path(folder),reader)
            result=provider.get({})
            self.assertEqual(result['items'],[])
            self.assertEqual(result['totals']['auctions'],0)
            self.assertEqual(provider.get({}),result)
            reader.assert_called_once()
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_detail_icon_metadata_and_distribution_truncation(self):
        reader=Mock(return_value=[{'kind':'totals','items':1,'auctions':1,'quantity':3},
            {'kind':'item','id':7,'displayid':9}, {'kind':'listing','id':5}]+
            [{'kind':'price','unit_price':n,'quantity':1} for n in range(201)])
        with tempfile.TemporaryDirectory() as folder:
            provider=AuctionProvider(Path(folder),reader);provider.metadata={'icons':{'9':'test_icon'}}
            result=provider.get({'id':['7']},True)
            self.assertEqual(result['items'][0]['icon'],'test_icon')
            self.assertTrue(result['prices_truncated'])
            self.assertEqual(len(result['prices']),200)
            self.assertEqual(result['listings'],[{'kind':'listing','id':5}])

    def test_database_error_is_safe_and_not_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            provider=AuctionProvider(Path(folder),Mock(side_effect=DatabaseError('secret')))
            with self.assertRaises(DatabaseError) as error:provider.get({})
            self.assertNotIn('secret',str(error.exception))
            self.assertFalse(provider.cached)

class AuctionHttpTests(unittest.TestCase):
    def test_assets_queries_validation_and_safe_outage(self):
        import json
        import threading
        from http.server import ThreadingHTTPServer
        from urllib.request import urlopen
        from urllib.error import HTTPError
        from unittest.mock import patch
        import dashboard
        with patch.object(AuctionProvider,'get',return_value={'items':[],'totals':{'items':0}}) as get:
            server=ThreadingHTTPServer(('127.0.0.1',0),dashboard.handler(dashboard.SnapshotCache(),0))
            server.RequestHandlerClass=dashboard.handler(dashboard.SnapshotCache(),server.server_port)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                for path in ['/auctions','/auctions.css','/auctions.js','/auction-categories.js','/auction-condensed.ttf']:
                    with urlopen(base+path) as response:
                        self.assertEqual(response.status,200)
                        self.assertIn("default-src 'self'",response.headers['Content-Security-Policy'])
                with urlopen(base+'/api/auctions?house=horde') as response:self.assertTrue(json.load(response)['ok'])
                get.assert_called_with({'house':['horde']},detail=False)
                with urlopen(base+'/api/auctions/item?id=7') as response:self.assertTrue(json.load(response)['ok'])
                get.assert_called_with({'id':['7']},detail=True)
                for exception,status in [(ValueError('Invalid filter'),400),(DatabaseError('Auction database unavailable'),503)]:
                    get.side_effect=exception
                    with self.assertRaises(HTTPError) as error:urlopen(base+'/api/auctions')
                    self.assertEqual(error.exception.code,status)
                    self.assertFalse(json.load(error.exception)['ok'])
            finally:server.shutdown();server.server_close();thread.join()
