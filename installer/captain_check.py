"""Native Mac acceptance of the real OpenCode -> captain -> worker pipeline."""
import argparse
import base64
import json
from pathlib import Path
import secrets
import subprocess
import time
from urllib.request import Request, urlopen
from turnkey_install import ReadinessError
from common import http, port_open, stop_process


def verify(root, config):
    started = int(time.time() * 1000)
    try:
        return _verify(root, config)
    except Exception as error:
        # Preserve the whole failed native turn, even for a normal final reply
        # which never dispatched. A later scoped retry must not need more logs.
        try:
            from acceptance_diagnostics import collect, save
            path = save(root / 'logs/native-acceptance/captain-diagnostic.json',
                        collect(root, since_ms=started, reason=error))
            detail = 'diagnostic=' + str(path)
        except Exception as diagnostic_error:
            detail = 'diagnostic capture failed: ' + str(diagnostic_error)
        raise ReadinessError(str(error) + '; ' + detail) from error


def _verify(root, config):
    if not config.get('captain', {}).get('enabled'):
        return []
    if port_open(4096):
        raise ReadinessError('Close the Work Agent before running captain acceptance')
    import work_agent
    from team_setup import verify_work_agent
    status = http('http://127.0.0.1:8001/control/mode', key=config['api_key'])
    if status['mode'] not in {'normal', 'max'} or status['transitioning'] or status['error']:
        raise ReadinessError('Captain acceptance requires a ready Normal or Max mode')
    models = http('http://127.0.0.1:8001/v1/models', key=config['api_key'])['data']
    settings = work_agent.configuration(config, [m['id'] for m in models], status['mode'], root, status)
    env = work_agent.environment(root, config, settings)
    env.update(OPENCODE_SERVER_USERNAME='opencode', OPENCODE_SERVER_PASSWORD=secrets.token_urlsafe(24))
    folder = root / 'work-agent/captain-acceptance'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'evidence.txt').write_text('The recorded acceptance value is 323.\n')
    token = base64.b64encode(('opencode:' + env['OPENCODE_SERVER_PASSWORD']).encode()).decode()
    def native(path, body=None, *, timeout=1800):
        request = Request('http://127.0.0.1:4096' + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Authorization': 'Basic ' + token, 'Content-Type': 'application/json'})
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    binary = root / 'tools/opencode' / work_agent.VERSION / 'opencode'
    with (root / 'logs/captain-acceptance.log').open('a') as log:
        process = subprocess.Popen([str(binary), 'serve', '--hostname', '127.0.0.1', '--port', '4096'],
                                   cwd=folder, env=env, stdout=log, stderr=log, start_new_session=True)
        try:
            verify_work_agent(process, env, True)
            session = native('/session', {'title': 'Native captain acceptance'})['id']
            tasks = [{'id': 'arithmetic', 'role': 'analyst', 'objective': 'Independently calculate 17 times 19.',
                      'constraints': 'Short answer. No commands or edits.', 'evidence': '17 * 20 - 17.',
                      'deliverable': 'The numerical result and one-sentence calculation.'},
                     {'id': 'file-check', 'role': 'reviewer', 'objective': 'Read evidence.txt and report its recorded value.',
                      'constraints': 'Use the native read tool. No commands or edits.', 'evidence': 'Project file evidence.txt.',
                      'deliverable': 'The recorded value with the file reference.'}]
            prompt = ('Native acceptance: call team_run exactly once with tasks set to this JSON array: '
                      + json.dumps(tasks) + '. Wait for both results, then read their reports and call team_retire '
                      'with ids arithmetic and file-check. Finally report the results and any failure. '
                      'Do not answer the arithmetic before dispatching.')
            started = time.monotonic()
            result = native('/session/' + session + '/message', {'agent': 'plan', 'parts': [{'type': 'text', 'text': prompt}]})
            if result.get('info', {}).get('error'):
                raise ReadinessError('Native captain response failed')
            messages = native('/session/' + session + '/message')
            parts = [p for m in messages for p in m['parts'] if p['type'] == 'tool']
            run = next((p for p in parts if p.get('tool') == 'team_run' and p.get('state', {}).get('status') == 'completed'), None)
            retire = next((p for p in parts if p.get('tool') == 'team_retire' and p.get('state', {}).get('status') == 'completed'), None)
            if not run or not retire:
                counts = {name: sum(p.get('tool') == name and p.get('state', {}).get('status') == 'completed'
                                    for p in parts) for name in ('team_run', 'team_retire')}
                raise ReadinessError('Native captain did not complete dispatch and retirement; '
                                     + ', '.join(name + '=' + str(count) for name, count in counts.items()))
            cohort = json.loads(run['state']['output'])
            if len(cohort.get('tasks', [])) != 2 or any(t.get('status') != 'completed' for t in cohort['tasks']):
                raise ReadinessError('Native captain worker did not complete its deliverable')
            for task in cohort['tasks']:
                report = json.loads(Path(task['report']).read_text())
                if '323' not in report['output']:
                    raise ReadinessError('Native worker returned the wrong arithmetic/evidence value')
                if task['id'] == 'file-check' and not any(p.get('tool') == 'read' and p.get('state', {}).get('status') == 'completed'
                                                        for p in report['native_tools']):
                    raise ReadinessError('Reviewer did not actually read the evidence file')
            checks = [{'name': 'native-captain-team', 'status': 'passed', 'workers': 2,
                     'seconds': round(time.monotonic() - started, 2),
                     'note': 'Verifies real dispatch/tool use/results/retirement; not a five-worker throughput benchmark.'}]
            from captain_conversation_check import verify_native
            conversation = verify_native(root, native=native, model_id=config['captain']['model_id'],
                                         startup_timeout=0, call_timeout=1800)
            if conversation['status'] != 'passed':
                raise ReadinessError('Native Captain conversation recovery failed: '
                    + conversation.get('issue', conversation['stage']) + '; report='
                    + str(root / 'logs/native-acceptance/conversation-repair-probe.json'))
            checks.append({'name': 'native-captain-conversation', 'status': 'passed',
                           'checks': conversation['checks'], 'scope': conversation['scope']})
            return checks
        finally:
            stop_process(process)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--usage', action='store_true', help='Print recorded workflow token usage without running acceptance')
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    config = json.loads((root / 'control/config.json').read_text())
    if args.usage:
        from urllib.request import build_opener, ProxyHandler
        from context_settings import NoRedirect
        request = Request('http://127.0.0.1:8001/control/usage', headers={'Authorization': 'Bearer ' + config['api_key']})
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=5) as response:
            print(json.dumps(json.load(response), indent=2))
        return
    result = verify(root, config)
    (root / 'captain-acceptance-report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
