"""LAN host allowlist keeps existing HTTP boundaries intact."""
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import dashboard


class LanHttpTests(unittest.TestCase):
    def test_explicit_lan_host_get_post_and_rejection_boundaries(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),dashboard.handler(fixture_cache(reader=lambda names:[]),0))
        port=server.server_port
        server.RequestHandlerClass=dashboard.handler(fixture_cache(reader=lambda names:[]),port,
                                                   allowed_hosts=['198.51.100.10'])
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{port}';host=f'198.51.100.10:{port}'
        try:
            with urlopen(Request(base+'/api/session',headers={'Host':host,'Origin':'http://'+host})) as response:
                session=json.load(response)
            req=Request(base+'/api/groups',data=json.dumps({'action':'select','id':'band'}).encode(),
                        headers={'Host':host,'Origin':'http://'+host,'Content-Type':'application/json',
                                 'X-Dashboard-Token':session['token']})
            with urlopen(req) as response:self.assertTrue(json.load(response)['ok'])
            for headers in [{'Host':f'198.51.100.11:{port}'}, {'Host':host,'Origin':'http://attacker.example'},
                            {'Host':host,'Sec-Fetch-Site':'cross-site'}, {'Host':'attacker.example'}]:
                with self.subTest(headers=headers),self.assertRaises(HTTPError) as exc:
                    urlopen(Request(base+'/api/session',headers=headers))
                self.assertEqual(exc.exception.code,403)
            req=Request(base+'/api/groups',data=b'{}',headers={'Host':host,'Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as exc:urlopen(req)
            self.assertEqual(exc.exception.code,403)
        finally:
            server.shutdown();server.server_close();thread.join()

from test_support import fixture_cache
