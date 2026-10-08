import {Client,GatewayIntentBits,ChannelType,ActionRowBuilder,ButtonBuilder,ButtonStyle,AttachmentBuilder} from 'discord.js';
import {joinVoiceChannel,createAudioPlayer,createAudioResource,StreamType,EndBehaviorType,VoiceConnectionStatus,AudioPlayerStatus,entersState} from '@discordjs/voice';
import * as dave from '@snazzah/davey';
import OpusScript from 'opusscript';
import {PassThrough} from 'node:stream';
import {randomUUID} from 'node:crypto';
import {permitted,pcmToDiscord,Downsample,PlaybackLedger,Capture,permissionDetails,isPrivateChannel} from './discord-core.mjs';

if(process.argv.includes('--check')){
  const codec=new OpusScript(48000,2,OpusScript.Application.AUDIO);
  const packet=codec.encode(Buffer.alloc(3840),960);if(codec.decode(packet).length!==3840 || !Object.keys(dave).length)throw Error('Codec check failed');
  codec.delete();console.log('Discord Opus and DAVE dependencies verified');process.exit(0);
}
let raw='';for await(const part of process.stdin){raw+=part;if(raw.length>32768)throw Error('Invalid bootstrap');}
const {token,config:c,bridgeKey}=JSON.parse(raw);raw='';
for(const name of ['owner_id','bot_id','guild_id','channel_id'])if(!/^[0-9]{15,22}$/.test(c[name]))throw Error('Invalid Discord configuration');
const client=new Client({intents:[GatewayIntentBits.Guilds,GatewayIntentBits.GuildVoiceStates],allowedMentions:{parse:[]}});
let call=null,serial=Promise.resolve(),closing=false,cursor=0,disconnected=false,retryAfter=0;
async function api(action,data={}){
  const r=await fetch('http://127.0.0.1:8003/api',{method:'POST',headers:{Authorization:'Bearer '+bridgeKey,'Content-Type':'application/json'},body:JSON.stringify({action,...data}),signal:AbortSignal.timeout(action==='transcribe'?90000:15000)});
  const value=await r.json();if(!r.ok)throw Error(value.error||'Conversation request failed');return value;
}
const button=(id,label,style=ButtonStyle.Secondary)=>new ButtonBuilder().setCustomId(id).setLabel(label).setStyle(style);
async function say(s,text){if(call!==s)return;await s.channel.send({content:String(text).slice(0,1900),allowedMentions:{parse:[]}});}
function silence(s){s.player.stop(true);s.stream?.destroy();s.stream=null;s.resource=null;s.ledger=null;}
function interrupt(s){
  if(s.interruptPromise)return s.interruptPromise;
  silence(s);s.generation+=1;s.interrupting=true;
  s.interruptPromise=(async()=>{const v=await api('interrupt');s.generation=Math.max(s.generation,v.generation);})().finally(()=>{s.interrupting=false;s.interruptPromise=null;});
  return s.interruptPromise;
}
async function stop(){const s=call;if(!s)return;call=null;silence(s);s.capture?.destroy();s.connection?.destroy();for(const message of s.permissions.values())message.edit({components:[]}).catch(()=>{});await api('stop').catch(()=>{});}
async function reconcile(){
  if(closing)return;
  const channel=await client.channels.fetch(c.channel_id);
  if(!channel?.members?.has(c.owner_id))disconnected=false;
  const allowed=!disconnected && channel?.type===ChannelType.GuildVoice && isPrivateChannel(channel,c) && channel.members.has(c.owner_id) && [...channel.members.keys()].every(id=>[c.owner_id,c.bot_id].includes(id));
  if(!allowed){await stop();return;}if(call || Date.now()<retryAfter)return;
  const s={channel,nonce:randomUUID().slice(0,8),player:createAudioPlayer(),generation:0,agent:'plan',permissions:new Map(),text:'',busy:false,interrupting:false};call=s;
  try{
    s.connection=joinVoiceChannel({channelId:c.channel_id,guildId:c.guild_id,adapterCreator:channel.guild.voiceAdapterCreator,selfDeaf:false,selfMute:false});
    s.connection.on('error',()=>fail(s));s.player.on('error',()=>fail(s));
    s.connection.on(VoiceConnectionStatus.Disconnected,()=>fail(s));
    await entersState(s.connection,VoiceConnectionStatus.Ready,20000);
    const started=await api('start',{voice:c.voice||'default'});s.generation=started.generation;s.connection.subscribe(s.player);
    await channel.send({content:'Local AI connected using your saved voice. Plan mode. Only your speech is processed. Utterances: up to 28 seconds.',components:[new ActionRowBuilder().addComponents(button(s.nonce+':stop','Stop answer'),button(s.nonce+':plan','Plan'),button(s.nonce+':build','Build'),button(s.nonce+':leave','Disconnect'))]});
    s.connection.receiver.speaking.on('start',id=>{if(id===c.owner_id && call===s && !s.busy)capture(s);});
    poll(s).catch(()=>fail(s));
  }catch{await fail(s);}
}
async function fail(s){if(call===s){retryAfter=Date.now()+30000;await say(s,'Discord conversation stopped. Check logs on the Mac; the connection will retry.').catch(()=>{});await stop();}}
function schedule(){serial=serial.then(reconcile).catch(()=>console.error('Discord connection check failed'));}
async function poll(s){
  while(call===s){
    if(s.ledger && s.resource){for(const ack of s.ledger.advance(s.resource.playbackDuration))await api('played',ack);}
    const data=await api('poll',{after:cursor});
    if(!data.active)throw Error('Conversation stopped');
    if(s.interrupting){await new Promise(r=>setTimeout(r,100));continue;}
    for(const e of data.events){
      cursor=e.seq;if(call!==s)return;if(e.generation<s.generation)continue;
      if(e.kind==='reset'){silence(s);s.generation=e.generation;s.text='';}
      if(e.generation!==s.generation)continue;
      if(e.kind==='text')s.text=(s.text+e.text).slice(0,200000);
      if(e.kind==='audio'){
        if(!s.stream){s.stream=new PassThrough();s.resource=createAudioResource(s.stream,{inputType:StreamType.Raw});s.ledger=new PlaybackLedger(e.generation);s.player.play(s.resource);}
        const pcm=Buffer.from(e.pcm,'base64');s.ledger.chunk(e.chunk,pcm.length);s.stream.write(pcmToDiscord(pcm));
      }
      if(e.kind==='phrase')s.ledger?.phrase(e.phrase);
      if(e.kind==='done'){
        s.stream?.end();
        if(s.text.length>1900)await s.channel.send({files:[new AttachmentBuilder(Buffer.from(s.text),{name:'response.txt'})]});
        else if(s.text)await say(s,s.text);
        s.text='';
      }
      if(['error','speech_error','status'].includes(e.kind))await say(s,e.message);
    }
    if(call!==s)return;
    const pending=new Set(data.permissions.map(p=>p.id));
    for(const [id,message] of s.permissions)if(!pending.has(id)){await message.edit({components:[]}).catch(()=>{});s.permissions.delete(id);}
    for(const p of data.permissions)if(!s.permissions.has(p.id)){
      const detail=permissionDetails(p), components=[button(s.nonce+':deny:'+p.id,'Deny',ButtonStyle.Danger)];
      if(detail.allow)components.unshift(button(s.nonce+':allow:'+p.id,'Allow once',ButtonStyle.Success));
      const message=await s.channel.send({content:'Tool approval required. Review the attached request before allowing.',files:[new AttachmentBuilder(Buffer.from(detail.allow?detail.full:'Request exceeds review limit. Deny this request.'),{name:'permission.json'})],components:[new ActionRowBuilder().addComponents(...components)]});s.permissions.set(p.id,message);
    }
    await new Promise(r=>setTimeout(r,100));
  }
}
function capture(s){
  s.busy=true;const state=new Capture(),down=new Downsample(),decoder=new OpusScript(48000,2,OpusScript.Application.AUDIO);
  const stream=s.connection.receiver.subscribe(c.owner_id,{end:{behavior:EndBehaviorType.AfterSilence,duration:700}});s.capture=stream;
  let chain=Promise.resolve(),first=true,failed=false;
  stream.on('data',packet=>{
    try{
      state.push(down.push(decoder.decode(packet)));
      chain=chain.then(async()=>{
        let batch;while(call===s && !state.confirmed && (batch=state.batch())){
          const result=await api('detect',{pcm:batch.toString('base64'),reset:first});first=false;
          if(state.detect(result.probabilities))await interrupt(s);
        }
      }).catch(()=>{failed=true;stream.destroy();});
    }catch{failed=true;stream.destroy();}
  });
  stream.once('error',()=>{failed=true;});
  stream.once('close',async()=>{
    try{
      await chain;if(call!==s)return;if(failed){await say(s,'Speech capture failed or exceeded 28 seconds. Please try a shorter utterance.');return;}
      if(!state.confirmed)return;
      const result=await api('transcribe',{pcm:state.pcm().toString('base64')});
      if(call!==s || !result.text?.trim())return;
      await say(s,'You: '+result.text);await api('submit',{text:result.text,agent:s.agent});
    }catch{await say(s,'Speech could not be processed. Please try again after specialist work finishes.').catch(()=>{});}
    finally{decoder.delete();s.capture=null;s.busy=false;}
  });
}
client.on('interactionCreate',async i=>{
  if(!i.isButton())return;const s=call;
  if(!s || !permitted(c,i.user.id,i.guildId,i.channelId) || !i.customId.startsWith(s.nonce+':')){await i.reply({content:'This control is not available to you or has expired.',flags:64});return;}
  await i.deferReply({flags:64});
  try{
    const [,action,id]=i.customId.split(':');
    if(action==='stop')await interrupt(s);
    else if(action==='plan'||action==='build')s.agent=action;
    else if(action==='leave'){disconnected=true;await stop();await i.editReply('Disconnected. Leave the voice channel and rejoin to reconnect.');return;}
    else if(['allow','deny'].includes(action)&&s.permissions.has(id))await api('permission',{id,reply:action==='allow'?'once':'reject'});
    else throw Error('Expired control');
    await i.editReply('Applied: '+action);
  }catch{await i.editReply('Action failed or request expired.');}
});
client.once('clientReady',()=>{if(client.user.id!==c.bot_id){shutdown();return;}schedule();});
client.on('voiceStateUpdate',schedule);client.on('channelUpdate',schedule);
client.on('error',()=>console.error('Discord client error'));
const retry=setInterval(schedule,30000);
async function shutdown(){if(closing)return;closing=true;clearInterval(retry);await stop().catch(()=>{});client.destroy();process.exit(0);}
process.on('SIGTERM',shutdown);process.on('SIGINT',shutdown);
setInterval(()=>{if(process.ppid===1)shutdown();},3000).unref();
await client.login(token).catch(()=>{console.error('Discord login failed. Run Connect Discord.command to check credentials.');process.exit(1);});
