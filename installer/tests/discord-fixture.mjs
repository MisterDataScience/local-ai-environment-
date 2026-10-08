// Deterministic transport fixture. No Discord network or model calls.
import {EventEmitter} from 'node:events';
import {Readable} from 'node:stream';
const owner='111111111111111111',guild='222222222222222222',channelId='333333333333333333',bot='444444444444444444';
let client,generation=0,seq=0,events=[],actions=[],approved=false,acked=false,denied=false;
const event=(kind,data={})=>events.push({seq:++seq,generation,kind,...data});
const interaction=(id,user=owner)=>({isButton:()=>true,user:{id:user},guildId:guild,channelId,customId:id,reply:async()=>{denied=true;},deferReply:async()=>{},editReply:async()=>{}});
const channel={type:2,guild:{ownerId:owner,voiceAdapterCreator:{}},members:new Map([[owner,{}]]),permissionOverwrites:{cache:new Map([[guild,{id:guild,deny:{has:()=>true},allow:{has:()=>false}}]])},
  async send(message){
    if(message.content?.startsWith('Local AI connected'))setTimeout(()=>receiver.speaking.emit('start',owner),5);
    if(message.content?.startsWith('Tool approval')){
      const id=message.components[0].items[0].id;
      setTimeout(()=>{client.emit('interactionCreate',interaction(id,'999999999999999999'));client.emit('interactionCreate',interaction(id));},5);
    }
    return {edit:async()=>{}};
  }};
export class Client extends EventEmitter{constructor(){super();client=this;this.user={id:bot};this.channels={fetch:async()=>channel};}async login(){setImmediate(()=>this.emit('clientReady'));}destroy(){}}
export const GatewayIntentBits={Guilds:1,GuildVoiceStates:2},ChannelType={GuildVoice:2},ButtonStyle={Secondary:2,Danger:4,Success:3};
export class ButtonBuilder{setCustomId(id){this.id=id;return this;}setLabel(){return this;}setStyle(){return this;}}
export class ActionRowBuilder{addComponents(...items){this.items=items;return this;}}
export class AttachmentBuilder{constructor(data,options){this.data=data;this.options=options;}}
const receiver={speaking:new EventEmitter(),subscribe:()=>Readable.from(Array.from({length:12},()=>Buffer.alloc(3840)))};
export function joinVoiceChannel(){const c=new EventEmitter();Object.assign(c,{receiver,subscribe(){},destroy(){}});return c;}
export function createAudioPlayer(){const p=new EventEmitter();return Object.assign(p,{play(){},stop(){}});}
export function createAudioResource(stream){stream.resume();return {playbackDuration:1000};}
export const StreamType={Raw:1},EndBehaviorType={AfterSilence:1},VoiceConnectionStatus={Ready:1,Disconnected:2},AudioPlayerStatus={Idle:1};
export async function entersState(){}
export class OpusScript{static Application={AUDIO:1};decode(data){return data;}delete(){}}
export default OpusScript;
globalThis.fetch=async(_url,options)=>{
  const body=JSON.parse(options.body);actions.push(body.action);
  let result={};
  if(body.action==='start')result={generation};
  if(body.action==='detect')result={probabilities:[.9,.9,.9,.9,.9,.9]};
  if(body.action==='interrupt'){generation++;event('reset');result={generation};}
  if(body.action==='transcribe')result={text:'Test my coordinator'};
  if(body.action==='submit'){generation++;event('reset');event('text',{text:'A spoken response'});event('audio',{pcm:Buffer.alloc(24000).toString('base64'),chunk:1,phrase:1});event('phrase',{phrase:1});event('done');result={generation};}
  if(body.action==='poll')result={active:true,events:events.filter(e=>e.seq>body.after),permissions:actions.includes('submit')&&!approved?[{id:'request1',permission:'bash',patterns:['pwd'],metadata:{command:'pwd'}}]:[]};
  if(body.action==='permission'){if(body.reply!=='once')throw Error('Unexpected reply');approved=true;}
  if(body.action==='played'&&body.phrase===1)acked=true;
  if(approved&&acked&&!globalThis.finished){globalThis.finished=true;setTimeout(()=>process.kill(process.pid,'SIGTERM'),5);}
  if(body.action==='stop')console.log('RESULT '+JSON.stringify({actions,approved,acked,denied}));
  return {ok:true,json:async()=>result};
};
