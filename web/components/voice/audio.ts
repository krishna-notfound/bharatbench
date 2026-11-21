// Browser audio helpers for the voice panel: mic capture (AudioWorklet), energy VAD, playback queue.

export interface MicFrame {
  pcm: ArrayBuffer; // 16 kHz mono PCM16 LE, 100 ms
  rms: number; // 0..1
}

export class MicCapture {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;

  async start(onFrame: (frame: MicFrame) => void): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    this.ctx = new AudioContext();
    await this.ctx.audioWorklet.addModule("/pcm-worklet.js");
    const source = this.ctx.createMediaStreamSource(this.stream);
    const node = new AudioWorkletNode(this.ctx, "pcm-capture");
    node.port.onmessage = (e: MessageEvent<MicFrame>) => onFrame(e.data);
    source.connect(node); // worklet outputs nothing; not connected to destination (no mic loopback)
  }

  stop(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close();
    this.stream = null;
    this.ctx = null;
  }
}

const START_THRESHOLD = 0.02;
const START_THRESHOLD_WHILE_SPEAKING = 0.06; // higher bar so the assistant's own audio does not self-interrupt
const ONSET_FRAMES = 2;
const HANGOVER_FRAMES = 6; // 600 ms
const PREROLL_FRAMES = 3; // 300 ms sent before onset
const TAIL_FRAMES = 3; // 300 ms of the hangover is sent as tail

export interface VadCallbacks {
  onSpeechStart: () => void;
  onFrame: (pcm: ArrayBuffer) => void; // frames to send to the server
  onSpeechEnd: () => void;
}

export class Vad {
  private speaking = false;
  private loud = 0;
  private quiet = 0;
  private preroll: ArrayBuffer[] = [];

  constructor(
    private readonly cb: VadCallbacks,
    private readonly assistantSpeaking: () => boolean,
  ) {}

  push(frame: MicFrame): void {
    const threshold = this.assistantSpeaking() ? START_THRESHOLD_WHILE_SPEAKING : START_THRESHOLD;
    const isLoud = frame.rms >= threshold;
    if (!this.speaking) {
      this.preroll.push(frame.pcm);
      if (this.preroll.length > PREROLL_FRAMES) this.preroll.shift();
      this.loud = isLoud ? this.loud + 1 : 0;
      if (this.loud >= ONSET_FRAMES) {
        this.speaking = true;
        this.quiet = 0;
        this.cb.onSpeechStart();
        this.preroll.forEach((p) => this.cb.onFrame(p));
        this.preroll = [];
      }
      return;
    }
    if (isLoud) {
      this.quiet = 0;
      this.cb.onFrame(frame.pcm);
      return;
    }
    this.quiet += 1;
    if (this.quiet <= TAIL_FRAMES) this.cb.onFrame(frame.pcm);
    if (this.quiet >= HANGOVER_FRAMES) {
      this.speaking = false;
      this.loud = 0;
      this.cb.onSpeechEnd();
    }
  }

  reset(): void {
    this.speaking = false;
    this.loud = 0;
    this.quiet = 0;
    this.preroll = [];
  }
}

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

export class PlaybackQueue {
  private ctx: AudioContext | null = null;
  private sources = new Set<AudioBufferSourceNode>();
  private nextTime = 0;
  private chain: Promise<void> = Promise.resolve();
  private generation = 0;

  constructor(private readonly onActiveChange: (active: boolean) => void) {}

  get active(): boolean {
    return this.sources.size > 0;
  }

  /** Must be called from a user gesture at least once so the context may run. */
  unlock(): void {
    this.ctx ??= new AudioContext();
    void this.ctx.resume();
  }

  enqueue(b64: string): void {
    const gen = this.generation;
    this.chain = this.chain.then(async () => {
      if (gen !== this.generation) return;
      this.unlock();
      const ctx = this.ctx;
      if (!ctx) return;
      let buffer: AudioBuffer;
      try {
        buffer = await ctx.decodeAudioData(base64ToArrayBuffer(b64));
      } catch {
        return;
      }
      if (gen !== this.generation) return;
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(ctx.destination);
      const start = Math.max(ctx.currentTime + 0.02, this.nextTime);
      this.nextTime = start + buffer.duration;
      this.sources.add(src);
      this.onActiveChange(true);
      src.onended = () => {
        this.sources.delete(src);
        if (this.sources.size === 0) this.onActiveChange(false);
      };
      src.start(start);
    });
  }

  /** Barge-in: stop everything now and drop anything still decoding. */
  stop(): void {
    this.generation += 1;
    this.sources.forEach((s) => {
      s.onended = null;
      try {
        s.stop();
      } catch {
        // already stopped
      }
    });
    this.sources.clear();
    this.nextTime = 0;
    this.onActiveChange(false);
  }
}
