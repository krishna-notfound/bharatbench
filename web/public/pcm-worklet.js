// AudioWorklet: downsample mic audio to 16 kHz mono PCM16 and post 100 ms frames (1600 samples) with RMS energy.
const TARGET_RATE = 16000;
const FRAME_SAMPLES = 1600;

class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE;
    this.position = 0; // fractional read position into the pending input
    this.pending = new Float32Array(0);
    this.out = new Float32Array(FRAME_SAMPLES);
    this.outLen = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;

    const merged = new Float32Array(this.pending.length + channel.length);
    merged.set(this.pending);
    merged.set(channel, this.pending.length);

    // Linear-interpolating resampler.
    let pos = this.position;
    while (pos + 1 < merged.length) {
      const i = Math.floor(pos);
      const frac = pos - i;
      this.out[this.outLen++] = merged[i] * (1 - frac) + merged[i + 1] * frac;
      pos += this.ratio;
      if (this.outLen === FRAME_SAMPLES) this.flush();
    }
    const consumed = Math.floor(pos);
    this.pending = merged.slice(consumed);
    this.position = pos - consumed;
    return true;
  }

  flush() {
    const pcm = new Int16Array(FRAME_SAMPLES);
    let sum = 0;
    for (let i = 0; i < FRAME_SAMPLES; i++) {
      const s = Math.max(-1, Math.min(1, this.out[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      sum += s * s;
    }
    this.port.postMessage({ pcm: pcm.buffer, rms: Math.sqrt(sum / FRAME_SAMPLES) }, [pcm.buffer]);
    this.outLen = 0;
  }
}

registerProcessor("pcm-capture", PcmCaptureProcessor);
