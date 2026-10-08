/* Resample device audio to bounded PCM16 batches at 16 kHz. No network here. */
class Microphone extends AudioWorkletProcessor {
  constructor() {
    super();
    this.sum = 0; this.weight = 0; this.remaining = sampleRate / 16000;
    this.samples = new Int16Array(3072); this.index = 0;
  }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    const ratio = sampleRate / 16000;
    for (const sample of input) {
      let available = 1;
      while (available > 1e-8) {
        const used = Math.min(available, this.remaining);
        this.sum += sample * used; this.weight += used;
        this.remaining -= used; available -= used;
        if (this.remaining < 1e-8) {
          this.samples[this.index++] = Math.round(Math.max(-1, Math.min(1, this.sum / this.weight)) * 32767);
          this.sum = 0; this.weight = 0; this.remaining = ratio;
          if (this.index === this.samples.length) {
            this.port.postMessage(this.samples.buffer, [this.samples.buffer]);
            this.samples = new Int16Array(3072); this.index = 0;
          }
        }
      }
    }
    return true;
  }
}
registerProcessor('microphone', Microphone);
