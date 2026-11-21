"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { OrbState } from "@/components/orb/orb";
import { API_URL } from "@/lib/api";
import { AudioScheduler } from "@/lib/audio/AudioScheduler";
import { InterruptionController } from "@/lib/audio/InterruptionController";
import { MicCapture } from "@/lib/audio/MicCapture";
import { VoiceActivityDetector } from "@/lib/audio/VoiceActivityDetector";
import { perfToEpochMs } from "@/lib/audio/vadCore";
import type { RunStatus } from "@/lib/types";
import { CaptionTrack, runCaptionLoop, type CaptionFrame } from "./CaptionTrack";
import { MAX_TEXT_CHARS, type ServerEvent, type VoiceState } from "./protocol";
import { RealtimeClient, type ConnectionStatus } from "./RealtimeClient";
import { loadLanguage, saveLanguage, type RealtimeLanguage } from "./languages";
import { getTokenSafe } from "./token";

export type { RealtimeLanguage };

export type RealtimeState = "idle" | "connecting" | "listening" | "thinking" | "working" | "speaking" | "offline";

export interface JobUpdate {
  runId: string;
  status: RunStatus;
  message: string;
  progress: number | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "tool" | "job" | "system";
  text: string;
  /** Assistant messages: server generation id, used to stream deltas into one bubble. */
  generationId?: number;
  interrupted?: boolean;
  streaming?: boolean;
  /** role "tool": the call, its friendly label and (once finished) whether it succeeded. */
  callId?: string;
  toolName?: string;
  ok?: boolean;
  /** role "job": the run whose latest status is in `jobs[runId]`. */
  runId?: string;
}

export interface Realtime {
  state: RealtimeState;
  orbState: OrbState;
  /** Current audio level 0..1 (assistant output while speaking, otherwise the microphone). */
  getLevel: () => number;
  transcript: Message[];
  connect: () => void;
  disconnect: () => void;
  sendText: (text: string) => void;
  toggleMic: () => Promise<void>;
  /** Stop the assistant locally, then cancel its turn on the server. */
  interrupt: () => void;
  conversationId: string | null;
  jobs: Record<string, JobUpdate>;
  connected: boolean;
  micOn: boolean;
  error: string | null;
  language: RealtimeLanguage;
  setLanguage: (language: RealtimeLanguage) => void;
  /** Drop the thread and the stored conversation id, then start fresh. */
  newConversation: () => void;
  /** Word-synced caption of the reply being spoken, or null. */
  caption: CaptionFrame | null;
}

const WS_URL = `${API_URL.replace(/^http/, "ws")}/ws/realtime`;
const CONVERSATION_KEY = "bb.agent.conversation.v1";
const MAX_MESSAGES = 200;

function loadConversationId(): string | null {
  try {
    return window.localStorage.getItem(CONVERSATION_KEY);
  } catch {
    return null;
  }
}

function saveConversationId(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(CONVERSATION_KEY, id);
    else window.localStorage.removeItem(CONVERSATION_KEY);
  } catch {
    // storage unavailable: the conversation just is not resumed next time
  }
}

function closeMessage(code: number): string {
  if (code === 4401) return "Your session expired. Please sign in again.";
  if (code === 4503) return "The agent is busy right now. Please try again in a moment.";
  return "I can't reach the voice service.";
}

function composeState(
  status: ConnectionStatus,
  offline: boolean,
  voice: VoiceState,
  micOn: boolean,
): RealtimeState {
  if (status !== "ready") {
    if (status === "connecting" || status === "reconnecting") return "connecting";
    return offline ? "offline" : "idle";
  }
  switch (voice) {
    case "LISTENING":
    case "INTERRUPTED":
      return "listening";
    case "PROCESSING":
    case "GENERATING":
      return "thinking";
    case "WORKING":
      return "working";
    case "SPEAKING":
      return "speaking";
    case "RECONNECTING":
      return "connecting";
    default:
      return micOn ? "listening" : "idle";
  }
}

function orbFor(state: RealtimeState, ducked: boolean): OrbState {
  if (ducked) return "listening";
  switch (state) {
    case "offline":
      return "error";
    case "listening":
      return "listening";
    case "thinking":
    case "working":
    case "connecting":
      return "thinking";
    case "speaking":
      return "speaking";
    default:
      return "idle";
  }
}

interface Engine {
  client: RealtimeClient;
  scheduler: AudioScheduler;
  interruption: InterruptionController;
  vad: VoiceActivityDetector;
  captions: CaptionTrack;
  stopCaptionLoop: () => void;
  mic: MicCapture | null;
  lastGeneration: number | null;
}

export function useRealtime(): Realtime {
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [voiceState, setVoiceState] = useState<VoiceState>("IDLE");
  const [transcript, setTranscript] = useState<Message[]>([]);
  const [jobs, setJobs] = useState<Record<string, JobUpdate>>({});
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [micOn, setMicOn] = useState(false);
  const [ducked, setDucked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [language, setLanguageState] = useState<RealtimeLanguage>("auto");
  const [caption, setCaption] = useState<CaptionFrame | null>(null);

  const engineRef = useRef<Engine | null>(null);
  const idRef = useRef(0);
  const languageRef = useRef<RealtimeLanguage>("auto");
  const micOnRef = useRef(false);

  const nextId = useCallback(() => `m${idRef.current++}`, []);

  const pushMessage = useCallback((message: Message) => {
    setTranscript((prev) => [...prev, message].slice(-MAX_MESSAGES));
  }, []);

  const teardown = useCallback(() => {
    const engine = engineRef.current;
    engineRef.current = null;
    if (!engine) return;
    engine.stopCaptionLoop();
    engine.mic?.stop();
    engine.vad.close();
    engine.scheduler.close();
    engine.client.end();
    micOnRef.current = false;
    setMicOn(false);
    setDucked(false);
    setCaption(null);
    setStatus("idle");
    setVoiceState("IDLE");
    setTranscript((prev) => prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)));
  }, []);

  const handleEvent = useCallback(
    (engine: Engine, event: ServerEvent) => {
      const { scheduler, interruption, captions } = engine;
      switch (event.type) {
        case "session.ready":
          setConversationId(event.conversation_id);
          saveConversationId(event.conversation_id);
          setError(null);
          setOffline(false);
          void scheduler.useOutputRate(event.output_sample_rate);
          break;
        case "state":
          setVoiceState(event.state);
          break;
        case "transcript.final":
          pushMessage({ id: nextId(), role: "user", text: event.text });
          break;
        case "llm.started":
          engine.lastGeneration = event.generation_id;
          break;
        case "text.delta": {
          engine.lastGeneration = event.generation_id;
          setTranscript((prev) => {
            const i = prev.findIndex((m) => m.role === "assistant" && m.generationId === event.generation_id);
            if (i === -1) {
              return [
                ...prev,
                { id: nextId(), role: "assistant", text: event.delta, generationId: event.generation_id, streaming: true } satisfies Message,
              ].slice(-MAX_MESSAGES);
            }
            return prev.map((m, j) => (j === i ? { ...m, text: m.text + event.delta } : m));
          });
          break;
        }
        case "turn.completed":
          setTranscript((prev) => {
            const i = prev.findIndex((m) => m.role === "assistant" && m.generationId === event.generation_id);
            if (i === -1) {
              if (!event.text) return prev;
              return [
                ...prev,
                { id: nextId(), role: "assistant", text: event.text, generationId: event.generation_id } satisfies Message,
              ].slice(-MAX_MESSAGES);
            }
            return prev.map((m, j) => (j === i ? { ...m, text: event.text || m.text, streaming: false } : m));
          });
          break;
        case "turn.cancelled":
          scheduler.stop();
          interruption.onCancelled();
          captions.freeze(performance.now());
          if (event.generation_id !== undefined) {
            setTranscript((prev) =>
              prev.map((m) =>
                m.role === "assistant" && m.generationId === event.generation_id
                  ? { ...m, interrupted: true, streaming: false }
                  : m,
              ),
            );
          }
          break;
        case "turn.resume":
          interruption.onResume();
          break;
        case "audio.started":
          if (scheduler.beginGeneration(event.generation_id, event.sample_rate)) {
            captions.begin(event.generation_id, event.sample_rate);
            interruption.reset();
          }
          break;
        case "audio.segment":
          captions.onSegment(event.generation_id, event.index, event.text, event.first_seq);
          break;
        case "audio.segment_done":
          captions.onSegmentDone(event.generation_id, event.index, event.samples);
          break;
        case "audio.completed":
          scheduler.markGenerationDone(event.generation_id);
          break;
        case "tool.started":
          pushMessage({
            id: nextId(),
            role: "tool",
            text: event.label,
            callId: event.call_id,
            toolName: event.name,
          });
          break;
        case "tool.finished":
          setTranscript((prev) =>
            prev.map((m) => (m.role === "tool" && m.callId === event.call_id ? { ...m, ok: event.ok } : m)),
          );
          break;
        case "job.update": {
          const update: JobUpdate = {
            runId: event.run_id,
            status: event.status,
            message: event.message,
            progress: event.progress,
          };
          setJobs((prev) => ({ ...prev, [event.run_id]: update }));
          setTranscript((prev) =>
            prev.some((m) => m.role === "job" && m.runId === event.run_id)
              ? prev
              : [...prev, { id: nextId(), role: "job", text: "", runId: event.run_id } satisfies Message].slice(-MAX_MESSAGES),
          );
          break;
        }
        case "pipeline.error":
          setError(event.message);
          break;
        default:
          break;
      }
    },
    [nextId, pushMessage],
  );

  const connect = useCallback(() => {
    if (engineRef.current) return;
    setError(null);
    setOffline(false);

    const scheduler = new AudioScheduler();
    // Created inside the user gesture that opened the panel so the browser lets audio start.
    void scheduler.init().catch(() => undefined);
    scheduler.setMuted(!micOnRef.current);

    const client = new RealtimeClient({
      url: WS_URL,
      getToken: getTokenSafe,
      language: languageRef.current,
      mode: "voice",
      conversationId: loadConversationId(),
    });
    const vad = new VoiceActivityDetector();
    const captions = new CaptionTrack();
    const interruption = new InterruptionController(scheduler, {
      lastVoicedAt: () => vad.lastVoicedAt,
      cancelTurn: (generationId) => client.cancelTurn(generationId),
      onDuckedChange: setDucked,
    });
    const engine: Engine = {
      client,
      scheduler,
      interruption,
      vad,
      captions,
      stopCaptionLoop: runCaptionLoop(captions, setCaption),
      mic: null,
      lastGeneration: null,
    };
    engineRef.current = engine;

    vad.events.on("speechStarted", (e) => {
      client.speechStarted(perfToEpochMs(e.onsetAt, performance.now(), Date.now()));
      interruption.onSpeechStarted(e.at, e.onsetAt);
    });
    vad.events.on("speechEnded", (e) => {
      client.speechEnded(perfToEpochMs(e.lastVoicedAt, performance.now(), Date.now()));
      interruption.onSpeechEnded(e.speechMs);
    });

    scheduler.events.on("chunk", (c) => captions.onChunkScheduled(c.generationId, c.seq, c.audibleAtMs));
    scheduler.events.on("audible", (id) => client.playbackStarted(id));
    scheduler.events.on("finished", (id) => {
      client.playbackFinished(id);
      interruption.reset();
    });

    client.events.on("reset", () => {
      scheduler.reset();
      interruption.reset();
      captions.reset();
    });
    client.events.on("status", setStatus);
    client.events.on("event", (event) => handleEvent(engine, event));
    client.events.on("audio", (frame) => {
      captions.onAudio(frame.generationId, frame.seq, frame.samples.length);
      scheduler.enqueue(frame.generationId, frame.seq, frame.samples);
    });
    client.events.on("closed", ({ code, byUser }) => {
      if (byUser) return;
      setError(closeMessage(code));
      setOffline(true);
      setMicOn(false);
      micOnRef.current = false;
      engine.mic?.stop();
      engine.mic = null;
      engine.vad.close();
      engine.scheduler.close();
      engine.stopCaptionLoop();
      engineRef.current = null;
    });

    client.connect();
  }, [handleEvent]);

  const disconnect = useCallback(() => {
    teardown();
  }, [teardown]);

  const sendText = useCallback(
    (raw: string) => {
      const text = raw.trim().slice(0, MAX_TEXT_CHARS);
      const engine = engineRef.current;
      if (!text || !engine?.client.sendText(text)) return;
      pushMessage({ id: nextId(), role: "user", text });
    },
    [nextId, pushMessage],
  );

  const toggleMic = useCallback(async () => {
    const engine = engineRef.current;
    if (!engine) return;
    if (micOnRef.current) {
      engine.vad.flush();
      engine.mic?.stop();
      engine.mic = null;
      micOnRef.current = false;
      engine.scheduler.setMuted(true);
      setMicOn(false);
      return;
    }
    const mic = new MicCapture((pcm, level) => {
      engine.client.sendAudio(pcm);
      engine.vad.process(level, engine.scheduler.isActive);
    });
    try {
      await mic.start();
    } catch {
      mic.stop();
      setError("Microphone access was blocked. You can still type.");
      return;
    }
    if (engineRef.current !== engine) {
      mic.stop();
      return;
    }
    engine.mic = mic;
    micOnRef.current = true;
    engine.scheduler.setMuted(false);
    void engine.scheduler.init().catch(() => undefined);
    setError(null);
    setMicOn(true);
  }, []);

  const interrupt = useCallback(() => {
    const engine = engineRef.current;
    if (!engine) return;
    const generationId = engine.scheduler.generationId ?? engine.lastGeneration;
    engine.scheduler.stop();
    engine.captions.freeze(performance.now());
    if (generationId !== null) engine.client.cancelTurn(generationId);
  }, []);

  const setLanguage = useCallback(
    (next: RealtimeLanguage) => {
      languageRef.current = next;
      setLanguageState(next);
      saveLanguage(next);
      if (engineRef.current) {
        teardown();
        connect();
      }
    },
    [connect, teardown],
  );

  const newConversation = useCallback(() => {
    const wasConnected = engineRef.current !== null;
    teardown();
    saveConversationId(null);
    setConversationId(null);
    setTranscript([]);
    setJobs({});
    setError(null);
    setOffline(false);
    if (wasConnected) connect();
  }, [connect, teardown]);

  useEffect(() => () => teardown(), [teardown]);

  // Restore the remembered language after hydration (the first render is always "auto" so SSR matches).
  useEffect(() => {
    const stored = loadLanguage();
    languageRef.current = stored;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reading localStorage must wait until after hydration
    setLanguageState(stored);
  }, []);

  const getLevel = useCallback((): number => {
    const engine = engineRef.current;
    if (!engine) return 0;
    return Math.max(engine.scheduler.level, engine.mic?.level ?? 0);
  }, []);

  const state = composeState(status, offline, voiceState, micOn);
  const orbState = orbFor(state, ducked);

  return useMemo(
    () => ({
      state,
      orbState,
      getLevel,
      transcript,
      connect,
      disconnect,
      sendText,
      toggleMic,
      interrupt,
      conversationId,
      jobs,
      connected: status === "ready",
      micOn,
      error,
      language,
      setLanguage,
      newConversation,
      caption,
    }),
    [
      state,
      orbState,
      getLevel,
      transcript,
      connect,
      disconnect,
      sendText,
      toggleMic,
      interrupt,
      conversationId,
      jobs,
      status,
      micOn,
      error,
      language,
      setLanguage,
      newConversation,
      caption,
    ],
  );
}
