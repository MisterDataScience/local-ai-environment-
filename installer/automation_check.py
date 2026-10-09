"""Real Mac smoke checks. Not a claim of coordinator end-to-end acceptance."""
import argparse
import fcntl
import json
from pathlib import Path
import sys
import time
from control_policy import Controller, Blocked, stop


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--external', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise Blocked('Real native acceptance requires a Mac')
    root = args.root.expanduser().resolve()
    cfg = json.loads((root / 'control/config.json').read_text())
    lock = (root / 'control/automation.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    workspace = root / 'work-agent/automation-acceptance'
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    browser = None
    if args.external:
        from delegation_browser import Browser
        browser = Browser(cfg.get('external_delegation', {}).get('selectors'))
    c = Controller(root, workspace, cfg, browser=browser)
    report = {'date': int(time.time()), 'native_smoke': 'pending',
              'coordinator_end_to_end': 'pending', 'external_submission': 'pending', 'checks': []}
    try:
        token = c.call('automation_begin', {})['session']
        c.call('desktop_folder', {'session': token, 'path': '.'})
        report['checks'].append('Finder returned the approved folder target')
        c.call('desktop_activate', {'session': token, 'app': 'Calculator'})
        report['checks'].append('Calculator activation command succeeded')
        for path in ('..', '/Users', '.private'):
            try:
                c.path(path)
            except Blocked:
                continue
            raise RuntimeError('Path restriction failed')
        report['checks'].append('Parent, absolute and hidden folder paths rejected')
        report['native_smoke'] = 'passed'
        if args.external:
            result = c.call('external_reason', {'session': token, 'question': 'logic'})
            if not result.get('untrusted_reference') or result.get('verified') is not False:
                raise RuntimeError('Response boundary failed')
            report['external_submission'] = 'response_retrieved_once_unverified'
            report['checks'].append('Approved catalog question retrieved; content omitted from report')
        stop(root)
        try:
            c.call('desktop_activate', {'session': token, 'app': 'Finder'})
        except Blocked:
            report['checks'].append('Emergency stop invalidated session; local rearm required')
        else:
            raise RuntimeError('Emergency stop failed')
    except Exception:
        report['failure'] = 'Native/browser operation blocked or failed; inspect locally. No automatic retry.'
        raise
    finally:
        # No prompts, response text, tokens, paths or native stderr in this report.
        from web_access import save
        save(root / 'automation-acceptance-report.json', report)
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
