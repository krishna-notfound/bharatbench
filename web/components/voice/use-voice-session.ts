"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { VoiceClientMessage, VoiceServerMessage } from "@/lib/types";
import { MicCapture, PlaybackQueue, Vad } from "./audio";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WS_URL = `${API_URL.replace(/^http/, "ws")}/ws/voice`;

export type VoiceLanguage = "auto" | "hi-IN" | "en-IN";
export type VoiceState = "idle" | "listening" | "thinking" | "speaking";

export interface TranscriptItem {
  id: number;
  role: "user" | "assistant" | "tool" | "system";
  text: string;
  turnId?: string;
}

export interface VoiceSession {
  state: VoiceState;
  connected: boolean;
  micOn: boolean;
  transcript: TranscriptItem[];
  error: string | null;
  language: VoiceLanguage;
  setLanguage: (l: VoiceLanguage) => void;
  connect: () => void;
  disconnect: () => void;
  toggleMic: () => Promise<void>;
  sendText: (text: string) => void;
}

export function useVoiceSession(): VoiceSession {
  const [connected, setConnected] = useState(false);
  const [micOn, setMicOn] = useState(false);
  const [turnActive, setTurnActive] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguageState] = useState<VoiceLanguage>("auto");

  const wsRef = useRef<WebSocket | null>(null);
  const micRef = useRef<MicCapture | null>(null);
  const turnActiveRef = useRef(false);
  const dropUntilTurnEnd = useRef(false); // after barge-in, ignore the cancelled turn's stragglers
  const idRef = useRef(0);
  const languageRef = useRef<VoiceLanguage>("auto");
  const playbackRef = useRef<PlaybackQueue | null>(null);

  const setTurn = useCallback((active: boolean) => {
    turnActiveRef.current = active;
    setTurnActive(active);
  }, []);

  const send = useCallback((msg: VoiceClientMessage) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }, []);

  const addItem = useCallback((item: Omit<TranscriptItem, "id">, mergeTurn = false) => {
    setTranscript((prev) => {
      const last = prev[prev.length - 1];
      if (mergeTurn && last && last.role === item.role && last.turnId && last.turnId === item.turnId) {
        return [...prev.slice(0, -1), { ...last, text: `${last.text} ${item.text}` }];
      }
      idRef.current += 1;
      return [...prev, { ...item, id: idRef.current }];
    });
  }, []);

  const getPlayback = useCallback((): PlaybackQueue => {
    playbackRef.current ??= new PlaybackQueue(setSpeaking);
    return playbackRef.current;
  }, []);

  const bargeIn = useCallback(() => {
    const playback = getPlayback();
    if (turnActiveRef.current) dropUntilTurnEnd.current = true;
    playback.stop();
    send({ type: "interrupt" });
  }, [getPlayback, send]);

  const handleMessage = useCallback(
    (msg: VoiceServerMessage) => {
      const turnScoped = msg.type === "assistant_text" || msg.type === "audio" || msg.type === "tool_call";
      if (dropUntilTurnEnd.current && (turnScoped || msg.type === "tool_result")) return;
      switch (msg.type) {
        case "ready":
          setError(null);
          break;
        case "transcript":
          if (msg.final) {
            addItem({ role: "user", text: msg.text });
            setTurn(true);
          }
          break;
        case "assistant_text":
          setTurn(true);
          addItem({ role: "assistant", text: msg.text, turnId: msg.turn_id }, true);
          break;
        case "tool_call":
          setTurn(true);
          addItem({ role: "tool", text: `Calling ${msg.name}` });
          break;
        case "tool_result":
          addItem({ role: "tool", text: `${msg.name}: ${msg.ok ? "ok" : "failed"} - ${msg.summary}` });
          break;
        case "audio":
          getPlayback().enqueue(msg.data);
          break;
        case "turn_end":
          setTurn(false);
          dropUntilTurnEnd.current = false;
          break;
        case "run_update":
          addItem({ role: "system", text: `Run ${msg.run_id}: ${msg.message}` });
          break;
        case "error":
          setError(msg.message);
          break;
      }
    },
    [addItem, getPlayback, setTurn],
  );

  const connect = useCallback(() => {
    if (wsRef.current) return;
    getPlayback().unlock();
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;
    ws.onopen = () => {
      setConnected(true);
      send({ type: "start", language: languageRef.current, run_id: null });
    };
    ws.onmessage = (e: MessageEvent<string>) => {
      try {
        handleMessage(JSON.parse(e.data) as VoiceServerMessage);
      } catch {
        setError("Received an unreadable message from the server");
      }
    };
    ws.onerror = () => setError("Could not reach the voice service");
    ws.onclose = () => {
      wsRef.current = null;
      setConnected(false);
      setTurn(false);
      micRef.current?.stop();
      micRef.current = null;
      setMicOn(false);
      playbackRef.current?.stop();
    };
  }, [getPlayback, handleMessage, send, setTurn]);

  const disconnect = useCallback(() => {
    wsRef.current?.close();
  }, []);

  const toggleMic = useCallback(async () => {
    if (micRef.current) {
      micRef.current.stop();
      micRef.current = null;
      setMicOn(false);
      return;
    }
    const playback = getPlayback();
    playback.unlock();
    const vad = new Vad(
      {
        onSpeechStart: () => {
          if (turnActiveRef.current || playback.active) bargeIn();
        },
        onFrame: (pcm) => {
          const ws = wsRef.current;
          if (ws && ws.readyState === WebSocket.OPEN) ws.send(pcm);
        },
        onSpeechEnd: () => {
          setTurn(true);
          send({ type: "speech_end" });
        },
      },
      () => playback.active,
    );
    const mic = new MicCapture();
    try {
      await mic.start((frame) => vad.push(frame));
    } catch {
      setError("Microphone permission denied or unavailable");
      return;
    }
    micRef.current = mic;
    setMicOn(true);
  }, [bargeIn, getPlayback, send, setTurn]);

  const sendText = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      if (turnActiveRef.current || playbackRef.current?.active) bargeIn();
      setTurn(true);
      send({ type: "text", text: trimmed });
    },
    [bargeIn, send, setTurn],
  );

  const setLanguage = useCallback(
    (l: VoiceLanguage) => {
      languageRef.current = l;
      setLanguageState(l);
      send({ type: "start", language: l, run_id: null });
    },
    [send],
  );

  useEffect(
    () => () => {
      micRef.current?.stop();
      playbackRef.current?.stop();
      wsRef.current?.close();
    },
    [],
  );

  let state: VoiceState = "idle";
  if (connected) {
    if (speaking) state = "speaking";
    else if (turnActive) state = "thinking";
    else if (micOn) state = "listening";
  }

  return {
    state, connected, micOn, transcript, error, language,
    setLanguage, connect, disconnect, toggleMic, sendText,
  };
}
