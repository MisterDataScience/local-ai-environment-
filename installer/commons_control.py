"""Owner entry point. Credentials remain local; opening the page starts no AI."""
import argparse
import json
from pathlib import Path
import subprocess
from urllib.parse import quote
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def main():
    parser=argparse.ArgumentParser(description="Open Village Commons, or send an explicit owner operation")
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--request',help='JSON owner operation; absent opens the browser without starting a session')
    args=parser.parse_args()
    config=json.loads((args.root/'control/config.json').read_text())
    base='http://127.0.0.1:'+str(config.get('gateway_port',8001))
    if args.request is None:
        subprocess.run(['/usr/bin/open',base+'/commons#'+quote(config['api_key'],safe='')],check=True)
        return
    value=json.loads(args.request)
    raw=json.dumps(value).encode()
    if len(raw)>65536: raise ValueError('Owner request is too large')
    request=Request(base+'/control/commons',data=raw,headers={'Authorization':'Bearer '+config['api_key'],'Content-Type':'application/json'})
    with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=30) as response:
        print(json.dumps(json.load(response),ensure_ascii=False,indent=2))


if __name__=='__main__': main()
