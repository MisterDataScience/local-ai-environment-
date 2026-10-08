/* Transport-independent bounds, conversion and Discord playback bookkeeping. */
export function permitted(config, user, guild, channel) {
  return user===config.owner_id && guild===config.guild_id && channel===config.channel_id;
}

export function pcmToDiscord(input) {
  if (!Buffer.isBuffer(input) || input.length%2 || input.length>24000) throw new Error('Invalid TTS chunk');
  // Qwen mono 24 kHz -> Discord stereo 48 kHz. Sample hold avoids a native codec dependency.
  const output=Buffer.alloc(input.length*4);
  for(let i=0;i<input.length;i+=2) for(let j=0;j<4;j++) output.writeInt16LE(input.readInt16LE(i),i*4+j*2);
  return output;
}

export class Downsample {
  constructor(){this.tail=Buffer.alloc(0);}
  push(input){
    const data=Buffer.concat([this.tail,input]), count=Math.floor(data.length/12), out=Buffer.alloc(count*2);
    for(let i=0;i<count;i++){
      let sum=0;for(let j=0;j<6;j++)sum+=data.readInt16LE(i*12+j*2);
      out.writeInt16LE(Math.round(sum/6),i*2);
    }
    this.tail=Buffer.from(data.subarray(count*12));return out;
  }
}

export class PlaybackLedger {
  constructor(generation){this.generation=generation;this.duration=0;this.pending=[];}
  chunk(id, bytes){this.duration+=bytes/48;this.pending.push({at:this.duration,chunk:id});}
  phrase(id){this.pending.push({at:this.duration,phrase:id});}
  advance(milliseconds){
    const ready=[];
    while(this.pending.length && this.pending[0].at<=milliseconds)ready.push({generation:this.generation,...this.pending.shift()});
    return ready.map(({at,...ack})=>ack);
  }
}

export class Capture {
  constructor(){this.parts=[];this.bytes=0;this.vad=Buffer.alloc(0);this.confirmed=false;this.voiced=0;}
  push(pcm){
    if(this.bytes+pcm.length>16000*2*28)throw new Error('Utterance exceeds 28 seconds');
    this.parts.push(pcm);this.bytes+=pcm.length;
    if(!this.confirmed)this.vad=Buffer.concat([this.vad,pcm]);
  }
  batch(){if(this.vad.length<6144)return null;const part=this.vad.subarray(0,6144);this.vad=Buffer.from(this.vad.subarray(6144));return part;}
  detect(probabilities){
    for(const p of probabilities){this.voiced=p>=.6?this.voiced+1:0;if(this.voiced>=3)this.confirmed=true;}
    return this.confirmed;
  }
  pcm(){return Buffer.concat(this.parts);}
}

export function permissionDetails(permission){
  const full=JSON.stringify({permission:permission.permission,patterns:permission.patterns,metadata:permission.metadata},null,2);
  return {full,allow:Buffer.byteLength(full)<=100000};
}

export function isPrivateChannel(channel, config, viewFlag=1024n){
  const everyone=channel.permissionOverwrites.cache.get(config.guild_id);
  if(!everyone || !everyone.deny.has(viewFlag))return false;
  for(const rule of channel.permissionOverwrites.cache.values()){
    if(rule.allow.has(viewFlag) && ![config.owner_id,config.bot_id].includes(rule.id))return false;
  }
  return channel.guild.ownerId===config.owner_id;
}
