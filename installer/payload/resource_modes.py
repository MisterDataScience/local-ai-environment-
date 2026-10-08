"""Server-enforced eligibility profiles, separate from the text model menu."""
import json
import os
import tempfile
from model_team import valid_profile

MODES = {'gaming': 'Coordinator/small text only; search and workspace/GitHub tools available.',
         'normal': 'Model team and eligible legacy text plus images and speech; video blocked.',
         'max': 'All configured text models, images, video and speech; sequential loading.'}


def allowed(mode, identifier, preset, route='text'):
    if mode == 'max':
        return True
    if route == 'video' or (mode == 'gaming' and route in {'image', 'speak'}):
        return False
    if valid_profile(preset):
        return mode == 'normal' or preset['role'] == 'coordinator'
    models = {'qwen3:4b'} if mode == 'gaming' else {'qwen3:4b', 'qwen3:14b'}
    return preset['model'] in models


def save(root, mode):
    fd, name = tempfile.mkstemp(prefix='.resource-mode-', dir=root)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump({'mode': mode}, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, root / 'resource-mode.json')
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load(root):
    path = root / 'resource-mode.json'
    # Preserve existing installations' capabilities until the owner selects a mode.
    mode = json.loads(path.read_text())['mode'] if path.exists() else 'max'
    if mode not in MODES:
        raise ValueError('Invalid saved resource mode; repair resource-mode.json before starting.')
    return mode


PAGE = '''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Local AI modes</title>
<style>body{font:18px system-ui;max-width:650px;margin:40px auto;padding:20px;background:#111827;color:#eee}button,select{font:inherit;padding:12px;margin:8px 0}p{line-height:1.5}#state{white-space:pre-line}</style></head>
<body><h1>Local AI modes</h1><p>This setting applies to every chat and device.</p>
<select id="mode"><option value="gaming">Gaming</option><option value="normal">Normal</option><option value="max">Max</option></select>
<button id="apply">Apply mode</button><p id="state">Connecting…</p>
<p>Gaming: coordinator/small text, short context, no image, video or speech generation.<br>Normal: model team and eligible text, plus images and speech.<br>Max: all configured models and media.</p>
<p>Search, GitHub and workspace tools remain available. Existing text inference may finish before memory is released. Wait for Ready before starting your game.</p>
<p>After changing modes, refresh Open WebUI and select an available model. Changing its model menu cannot override this setting.</p>
<script>
const key=decodeURIComponent(location.hash.slice(1));history.replaceState(null,'',location.pathname);
const state=document.querySelector('#state'),select=document.querySelector('#mode'),button=document.querySelector('#apply');
async function api(method='GET',mode){const r=await fetch('/control/mode',{method,cache:'no-store',headers:{'Authorization':'Bearer '+key,'Content-Type':'application/json'},...(mode?{body:JSON.stringify({mode})}:{})});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d;}
async function poll(){try{const d=await api();state.textContent=d.mode.toUpperCase()+' · '+(d.transitioning?'Switching; new inference blocked':d.error?'Blocked: '+d.error:'Ready')+'\n'+d.description;if(!select.dataset.edited)select.value=d.mode;}catch(e){state.textContent=e.message;}}
select.onchange=()=>select.dataset.edited='yes';button.onclick=async()=>{button.disabled=true;try{await api('POST',select.value);delete select.dataset.edited;await poll();}catch(e){state.textContent=e.message;}finally{button.disabled=false;}};
if(!key){state.textContent='Open AI Modes.command on your Mac while Local AI is running.';button.disabled=true;}else{poll();setInterval(poll,2000);}
</script></body></html>'''

