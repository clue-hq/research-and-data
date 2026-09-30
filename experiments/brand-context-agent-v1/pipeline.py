"""Run individual resumable stages. One process owns the store lock."""
import argparse
import concurrent.futures
from pathlib import Path
from dotenv import dotenv_values
from core import Store, require_exclusive_run
from providers import Providers
from assets import AssetPipeline
from knowledge import KnowledgePipeline

def main():
 p=argparse.ArgumentParser()
 p.add_argument('stage',choices=['acquire','classify','knowledge','retrieval','build'])
 p.add_argument('--env',type=Path,default=Path('../../.env'))
 p.add_argument('--run',default='conduit-20260919')
 a=p.parse_args()
 if '/' in a.run or '..' in a.run:raise ValueError('Invalid run name')
 s=Store(Path(__file__).parent/'runs'/a.run)
 lock=require_exclusive_run(s)
 providers=Providers(s,dotenv_values(a.env))
 assets=AssetPipeline(s,providers)
 if a.stage=='acquire':
  with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
   fs={pool.submit(f):name for name,f in [('website',assets.website),('logos',assets.brandfetch),('ads',assets.ads)]}
   for f in concurrent.futures.as_completed(fs):
    try:
     f.result()
     print('Acquisition checkpoint:',fs[f],flush=True)
    except Exception as e:
     s.write(fs[f]+'-failure.json',{'error':str(e)[:300]})
     print('Acquisition failure:',fs[f],type(e).__name__,flush=True)
 elif a.stage=='classify':assets.classify()
 elif a.stage=='knowledge':KnowledgePipeline(s,providers).synthesize()
 elif a.stage=='retrieval':
  from retrieval import evaluate
  evaluate(s,providers)
 elif a.stage=='build':
  from viewer import build
  build(s)
 lock.close()

if __name__=='__main__':main()
