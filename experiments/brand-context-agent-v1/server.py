"""Local-only static preview, bound to loopback and restricted to public output."""
import argparse
from functools import partial
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
class Handler(SimpleHTTPRequestHandler):
 def end_headers(self):
  self.send_header('X-Content-Type-Options','nosniff')
  self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
  self.send_header('Cache-Control','no-store')
  if self.path.startswith('/originals/'):
   self.send_header('Content-Disposition','attachment')
  super().end_headers()
 def list_directory(self,path):self.send_error(404);return None
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=3045);p.add_argument('--run',default='conduit-20260919');a=p.parse_args()
 if '/' in a.run or '..' in a.run:raise ValueError('Invalid run name')
 directory=Path(__file__).parent/'runs'/a.run/'public'
 print('Standalone review: http://localhost:'+str(a.port),flush=True)
 ThreadingHTTPServer(('127.0.0.1',a.port),partial(Handler,directory=str(directory))).serve_forever()
