import concurrent.futures
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import http.client
import json
import sys
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from commons_transport import Turn
from inference_scheduler import ModelQueue


class TransportTests(unittest.TestCase):
    def test_remote_providers_and_tool_delegation_never_open_a_socket(self):
        t=Turn(time.monotonic()+5)
        with patch('commons_transport.http.client.HTTPConnection') as connection:
            for base,path,payload in [('https://api.example.com','/v1/chat/completions',{}),
                                      ('http://127.0.0.1:11437','/other',{}),
                                      ('http://127.0.0.1:11437','/v1/chat/completions',{'tools':[{}]})]:
                with self.assertRaises((RuntimeError,PermissionError)):t.api(base,path,payload)
            connection.assert_not_called()

    def test_actual_stalled_http_inference_socket_can_be_cancelled(self):
        arrived,release=threading.Event(),threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                arrived.set();release.wait(5)
                try:
                    self.send_response(200);self.end_headers();self.wfile.write(b'{}')
                except OSError:pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        original=http.client.HTTPConnection
        t=Turn(time.monotonic()+10)
        def local(host,port,timeout):
            self.assertEqual((host,port),('127.0.0.1',11437))
            return original('127.0.0.1',server.server_port,timeout=timeout)
        pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            with patch('commons_transport.http.client.HTTPConnection',side_effect=local):
                future=pool.submit(t.api,'http://127.0.0.1:11437','/v1/chat/completions',{'messages':[]})
                self.assertTrue(arrived.wait(2));t.cancel()
                with self.assertRaises(Exception):future.result(2)
                self.assertTrue(future.done())
        finally:
            release.set();pool.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_cancelled_shared_queue_ticket_releases_without_admission(self):
        queue=ModelQueue();cancel=threading.Event();entered=threading.Event()
        def wait():
            with queue.lease(('captain','shared'),5,cancelled=cancel):entered.set()
        with queue.lease():
            pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future=pool.submit(wait)
            limit=time.monotonic()+2
            while queue.status()['waiting']!=1 and time.monotonic()<limit:time.sleep(.01)
            cancel.set()
            with self.assertRaises(RuntimeError):future.result(2)
            self.assertFalse(entered.is_set());self.assertEqual(queue.status()['waiting'],0)
            pool.shutdown()


if __name__=='__main__':unittest.main()
