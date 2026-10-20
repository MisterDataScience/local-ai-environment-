"""Open the owner institution page. Opening creates no model work."""
import argparse
import json
from pathlib import Path
import subprocess
from urllib.parse import quote
from urllib.request import Request,build_opener,ProxyHandler
from commons_control import NoRedirect


def main():
    parser=argparse.ArgumentParser(description='Village institutions and studios')
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--request',help='Explicit JSON owner operation; absent opens the page')
    args=parser.parse_args();config=json.loads((args.root/'control/config.json').read_text())
    base='http://127.0.0.1:'+str(config.get('gateway_port',8001))
    if not args.request:
        subprocess.run(['/usr/bin/open',base+'/institutions#'+quote(config['api_key'],safe='')],check=True);return
    data=json.dumps(json.loads(args.request)).encode()
    if len(data)>1024*1024:raise ValueError('Request too large')
    req=Request(base+'/control/studios',data=data,headers={'Authorization':'Bearer '+config['api_key'],'Content-Type':'application/json'})
    with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=1000) as response:print(json.dumps(json.load(response),indent=2))


if __name__=='__main__':main()
