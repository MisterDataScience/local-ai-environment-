export class Endpoint {
  constructor() { this.reset(); }
  reset() { this.active = false; this.voiced = 0; this.silent = 0; this.frames = 0; }
  update(probabilities) {
    let start = false, end = false;
    for (const p of probabilities) {
      if (p >= .6) { this.voiced++; this.silent = 0; }
      else if (p < .35) { this.silent++; if (!this.active) this.voiced = 0; }
      if (!this.active && this.voiced >= 3) { this.active = true; start = true; }
      if (this.active) this.frames++;
      if (this.active && (this.silent >= 22 || this.frames >= 875)) end = true;
    }
    const valid = this.voiced >= 8;
    return {start, end, valid};
  }
}

export function encodePCM(parts) {
  let bytes = '';
  for (const part of parts) {
    const view = new DataView(part.buffer, part.byteOffset, part.byteLength);
    for (let i = 0; i < view.byteLength; i++) bytes += String.fromCharCode(view.getUint8(i));
  }
  return btoa(bytes);
}

if (typeof document !== 'undefined') {
  const $ = id => document.getElementById(id);
  const key = location.hash.slice(1);
  history.replaceState(null, '', '/');
  const api = async (action, data = {}) => {
    const response = await fetch('/api', {method:'POST', headers:{'Content-Type':'application/json', Authorization:'Bearer '+key},
      body:JSON.stringify({action,...data})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Local connection failed');
    return result;
  };
  let active = false, muted = false, media, capture, playback, node, sources = new Set(), playAt = 0;
  let cursor = 0, generation = 0, polling = false, answer, micQueue = [], processing = false;
  let utterance = [], preRoll = [], held = false, endpoint = new Endpoint(), preview, lastPreview = 0;
  let micEpoch = 0, finalizing = false, resetVad = true, playbackEpoch = 0, pendingTimers = new Set();
  let changing = 0, ownsConnection = false;
  const status = text => { $('status').textContent = text; };
  const log = (role, text) => {
    const item = document.createElement('article'); item.textContent = role + ': ' + text;
    $('log').append(item); item.scrollIntoView({block:'nearest'}); return item;
  };
  function stopPlayback() {
    playbackEpoch++;
    for (const source of sources) { source.onended = null; try { source.stop(); } catch {} }
    sources.clear();
    for (const timer of pendingTimers) clearTimeout(timer);
    pendingTimers.clear(); playAt = 0;
  }
  async function interrupt() {
    stopPlayback();
    changing++;
    try { const result = await api('interrupt'); generation = Math.max(generation,result.generation); answer = null; }
    finally { changing--; }
  }
  function later(callback, seconds) {
    const epoch = playbackEpoch;
    const target = playback.currentTime + Math.max(0,seconds);
    function check() {
      if (epoch !== playbackEpoch || !playback) return;
      if (playback.state === 'running' && playback.currentTime >= target) { callback(); return; }
      const timer = setTimeout(()=>{pendingTimers.delete(timer);check();},100);
      pendingTimers.add(timer);
    }
    check();
  }
  function play(event) {
    const raw = atob(event.pcm), bytes = Uint8Array.from(raw, c => c.charCodeAt(0)), view = new DataView(bytes.buffer);
    const buffer = playback.createBuffer(1, bytes.length/2, 24000), floats = buffer.getChannelData(0);
    for (let i=0; i<floats.length; i++) floats[i] = view.getInt16(i*2, true)/32768;
    const source = playback.createBufferSource(); source.buffer = buffer; source.connect(playback.destination);
    const start = Math.max(playback.currentTime + .035, playAt); playAt = start + buffer.duration;
    sources.add(source);
    source.onended = () => { sources.delete(source); api('played', {generation:event.generation,chunk:event.chunk}).catch(fail); };
    source.start(start);
  }
  function permissionCards(permissions) {
    const ids = JSON.stringify(permissions.map(p=>p.id));
    if ($('permissions').dataset.ids === ids) return;
    $('permissions').dataset.ids = ids; $('permissions').replaceChildren();
    for (const p of permissions) {
      const card = document.createElement('div'), details = document.createElement('pre');
      details.textContent = p.permission + '\n' + JSON.stringify({patterns:p.patterns,metadata:p.metadata}, null, 2);
      card.append(details);
      for (const [label, reply] of [['Allow once','once'],['Deny','reject']]) {
        const button = document.createElement('button'); button.textContent = label;
        button.onclick = () => api('permission', {id:p.id,reply}).then(()=>card.remove()).catch(fail);
        card.append(button);
      }
      $('permissions').append(card);
    }
  }
  async function poll() {
    if (polling || !active) return;
    polling = true;
    try {
      const result = await api('poll', {after:cursor});
      if (!active || changing) return;
      if (!result.active) throw new Error('Conversation ended or disconnected. Start again.');
      for (const e of result.events) {
        cursor = e.seq;
        if (e.generation < generation) continue;
        if (e.kind === 'reset') { generation = e.generation; stopPlayback(); answer = null; continue; }
        if (e.generation !== generation) continue;
        if (e.kind === 'user') log('You', e.text);
        if (e.kind === 'text') { answer ||= log('Assistant',''); answer.textContent += e.text; }
        if (e.kind === 'audio') play(e);
        if (e.kind === 'phrase') later(() => api('played',{generation:e.generation,phrase:e.phrase}).catch(fail), playAt-playback.currentTime);
        if (e.kind === 'done') status('Listening.');
        if (e.kind === 'error' || e.kind === 'speech_error' || e.kind === 'status') status(e.message);
      }
      permissionCards(result.permissions);
    } catch (error) { await fail(error); }
    finally { polling = false; }
  }
  setInterval(poll, 250);
  async function fail(error) { await shutdown(); status(error.message); }
  async function shutdown() {
    const shouldStop = ownsConnection; ownsConnection = false;
    active = false; micEpoch++; held = false; endpoint.reset(); utterance=[]; micQueue=[]; preRoll=[];
    stopPlayback(); media?.getTracks().forEach(t=>t.stop()); node?.disconnect();
    await capture?.close().catch(()=>{}); await playback?.close().catch(()=>{});
    capture = playback = null; media = null;
    for (const id of ['stop','mute','interrupt','talk','send']) $(id).disabled = true;
    $('start').disabled = false;
    if (shouldStop) { try { await api('stop'); } catch {} }
  }
  function resetInput() { micEpoch++; endpoint.reset(); utterance=[]; preRoll=[]; micQueue=[]; resetVad=true; }
  async function commit(parts, epoch) {
    if (!parts.length || finalizing) return;
    finalizing = true;
    try {
      await preview;
      if (!active || epoch !== micEpoch) return;
      status('Transcribing…');
      const pcm = encodePCM(parts);
      let result;
      for (let attempt=0; attempt<60; attempt++) {
        if (!active || epoch !== micEpoch) return;
        try { result = await api('transcribe',{pcm}); break; }
        catch(error) {
          if (!/paused for specialist|worker busy/i.test(error.message) || attempt===59) throw error;
          status('Waiting for the active model to release memory…');
          await new Promise(resolve=>setTimeout(resolve,1000));
        }
      }
      if (!active || epoch !== micEpoch) return;
      $('caption').textContent = result.text;
      if (result.text) {
        changing++;
        try { const response = await api('submit',{text:result.text,agent:$('agent').value});
          generation = Math.max(generation,response.generation); status('Working…'); }
        finally { changing--; }
      } else status('No speech recognised. Try again.');
    } catch(error) { status(error.message); }
    finally { finalizing = false; }
  }
  function partial() {
    if (preview || utterance.length < 10 || performance.now()-lastPreview < 2000) return;
    const epoch = micEpoch, pcm = encodePCM(utterance); lastPreview = performance.now();
    preview = api('transcribe',{pcm}).then(r=> { if (epoch===micEpoch && active) $('caption').textContent = r.text+' …'; })
      .catch(()=>{}).finally(()=>{preview=null;});
  }
  async function frames(part) {
    if (!active || muted || finalizing) return;
    if ($('input').value === 'ptt') {
      if (held) { utterance.push(part); partial(); if (utterance.length >= 145) await release(); }
      return;
    }
    if (micQueue.length >= 3) { resetInput(); status('Microphone processing fell behind. Use push to talk or wait for the active job.'); return; }
    micQueue.push(part);
    if (processing) return;
    processing = true;
    try {
      while (active && micQueue.length) {
        const chunk = micQueue.shift(), epoch = micEpoch;
        const result = await api('detect', {pcm:encodePCM([chunk]),reset:resetVad}); resetVad=false;
        if (epoch !== micEpoch || muted) continue;
        const state = endpoint.update(result.probabilities);
        if (state.start) { utterance = [...preRoll]; await interrupt(); status('Listening to you…'); }
        if (endpoint.active) { utterance.push(chunk); partial(); }
        preRoll.push(chunk); if (preRoll.length>2) preRoll.shift();
        if (state.end) {
          const parts = utterance; utterance=[]; endpoint.reset(); preRoll=[];
          if (state.valid) await commit(parts, epoch);
        }
      }
    } catch(error) { resetInput(); status(error.message); }
    finally { processing=false; }
  }
  $('start').onclick = async () => {
    $('start').disabled = true;
    try {
      playback = new AudioContext(); await playback.resume();
      media = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
      capture = new AudioContext(); await capture.audioWorklet.addModule('/microphone.js');
      node = new AudioWorkletNode(capture,'microphone');
      capture.createMediaStreamSource(media).connect(node); node.connect(capture.destination);
      const result = await api('start',{voice:$('voice').value}); generation=result.generation;
      ownsConnection=true;
      active=true; muted=false; resetInput(); $('mute').textContent='Mute microphone';
      node.port.onmessage = e => frames(new Int16Array(e.data)); await capture.resume();
      for (const id of ['stop','mute','interrupt','send']) $(id).disabled=false;
      $('talk').disabled = $('input').value!=='ptt';
      const aec = media.getAudioTracks()[0].getSettings().echoCancellation;
      status(aec ? 'Listening. Echo cancellation enabled.' : 'Listening. Echo cancellation is unconfirmed; use headphones or push to talk.');
    } catch(error) { await fail(error); }
  };
  $('stop').onclick = () => shutdown().then(()=>status('Conversation ended. Microphone off.'));
  $('interrupt').onclick = () => interrupt().catch(fail);
  $('mute').onclick = () => { muted=!muted; media.getTracks().forEach(t=>t.enabled=!muted); resetInput(); $('mute').textContent=muted?'Unmute microphone':'Mute microphone'; status(muted?'Microphone muted.':'Listening.'); };
  $('input').onchange = () => { resetInput(); held=false; $('talk').disabled=!active || $('input').value!=='ptt'; };
  async function hold() { if (!active || muted || held || finalizing) return; resetInput(); held=true; try { await interrupt(); status('Listening to you…'); } catch(error) { await fail(error); } }
  async function release() { if (!held) return; held=false; const parts=utterance; utterance=[]; await commit(parts,micEpoch); }
  $('talk').onpointerdown = e => { e.preventDefault(); $('talk').setPointerCapture(e.pointerId); hold(); };
  $('talk').onpointerup = release; $('talk').onpointercancel = () => { held=false; resetInput(); };
  $('talk').onkeydown = e => { if (e.code==='Space' && !e.repeat) { e.preventDefault(); hold(); } };
  $('talk').onkeyup = e => { if(e.code==='Space') {e.preventDefault(); release();} };
  $('typed').onsubmit = async e => {e.preventDefault(); resetInput(); stopPlayback(); changing++; try { const r=await api('submit',{text:$('text').value,agent:$('agent').value});generation=Math.max(generation,r.generation); $('text').value='';status('Working…'); }catch(error){status(error.message);}finally{changing--;} };
  window.addEventListener('pagehide',()=>{media?.getTracks().forEach(t=>t.stop()); if(ownsConnection) fetch('/api',{method:'POST',keepalive:true,headers:{'Content-Type':'application/json',Authorization:'Bearer '+key},body:JSON.stringify({action:'stop'})}).catch(()=>{});});
  if (!key) { $('start').disabled=true; status('Open the private link printed by Start Conversation.command.'); }
}
