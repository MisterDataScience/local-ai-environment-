"""Open the local mode selector without saving its API credential in a page."""
import argparse
import json
from pathlib import Path
import subprocess
from urllib.parse import quote


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads((args.root / 'control/config.json').read_text())
    # Fragment stays in the browser, is removed immediately, and is never sent
    # in HTTP requests/logs. The page keeps the credential only in memory.
    url = 'http://127.0.0.1:' + str(config.get('gateway_port', 8001)) + '/modes#' + quote(config['api_key'], safe='')
    subprocess.run(['/usr/bin/open', url], check=True)


if __name__ == '__main__':
    main()
