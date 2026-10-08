"""Native audio smoke test and timings; run with Local AI ready and voice configured."""
import argparse
import audioop
import base64
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import time
import threading
from urllib.request import Request, urlopen
from conversation import request


def check(root):
    config = json.loads((root / 'control/config.json').read_text())
    headers = {'Authorization': 'Bearer ' + config['api_key'], 'Content-Type': 'application/json'}
    url = 'http://127.0.0.1:8001/conversation/audio'
    report = {'status': 'running', 'tested_at': time.time(),
              'interactive_acceptance': 'not_run', 'note': 'Timings include cold loads. This does not test echo cancellation, native tool approval or barge-in.'}
    stopping = threading.Event()
    def heartbeat():
        while not stopping.wait(3):
            try:
                request(url, {'action':'heartbeat'}, headers, timeout=5)
            except Exception:
                return
    try:
        state = request(url, {'action': 'heartbeat'}, headers)
        if state['enabled']:
            raise RuntimeError('End the active conversation before running its diagnostic')
        request(url, {'action': 'start'}, headers)
        threading.Thread(target=heartbeat, daemon=True).start()
        sentence = 'This is a local conversation check.'
        started = time.monotonic(); chunks = []
        req = Request(url, data=json.dumps({'action': 'speak', 'voice': 'default', 'text': sentence}).encode(), headers=headers)
        with urlopen(req, timeout=180) as response:
            done = False
            for line in response:
                event = json.loads(line)
                if event.get('error'): raise RuntimeError(event['error'])
                if event.get('done'): done = True; break
                if not chunks: report['tts_first_chunk_seconds'] = time.monotonic()-started
                chunks.append(base64.b64decode(event['pcm'], validate=True))
        if not chunks or not done: raise RuntimeError('Speech produced no complete audio stream')
        pcm = b''.join(chunks)
        report['tts_total_seconds'] = time.monotonic()-started
        report['audio_seconds'] = len(pcm)/48000
        report['tts_real_time_factor'] = report['tts_total_seconds']/report['audio_seconds']
        pcm16, _ = audioop.ratecv(pcm, 2, 1, 24000, 16000, None)
        started = time.monotonic()
        result = request(url, {'action':'transcribe', 'pcm':base64.b64encode(pcm16).decode()}, headers)
        report['stt_seconds'] = time.monotonic()-started
        report['transcript'] = result['text']
        norm = lambda s: re.sub(r'[^a-z ]', '', s.lower()).strip()
        report['transcript_similarity'] = SequenceMatcher(None, norm(sentence), norm(result['text'])).ratio()
        if report['transcript_similarity'] < .65: raise RuntimeError('Speech round trip did not recover the diagnostic sentence')
        speech_detected = False
        for offset in range(0, len(pcm16)-1023, 6144):
            block = pcm16[offset:offset+6144]
            block = block[:len(block)//1024*1024]
            if not block: continue
            result = request(url, {'action':'detect', 'pcm':base64.b64encode(block).decode(), 'reset':offset==0}, headers)
            speech_detected |= any(p >= .6 for p in result['probabilities'])
        if not speech_detected: raise RuntimeError('Voice detector did not recognise generated speech')
        report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error=str(error))
    finally:
        stopping.set()
        # Do not stop someone else's already-active conversation.
        if 'state' in locals() and not state['enabled']:
            try:
                request(url, {'action':'stop'}, headers)
            except Exception as error:
                report.update(status='failed', cleanup_error=str(error))
        path = root / 'conversation-check.json'
        path.write_text(json.dumps(report, indent=2)+'\n'); path.chmod(0o600)
    print(json.dumps(report, indent=2))
    print('Report:', path)
    return report['status'] == 'passed'


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    raise SystemExit(0 if check(args.root) else 1)
