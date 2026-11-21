// Languages offered in every selector: the intersection of Sarvam STT (saaras:v4) and TTS (bulbul:v3).
// Verified list and sources: api/app/voice/SARVAM_NOTES.md. Keep in sync with api/app/voice/languages.py.

export const SPOKEN_LANGUAGES = [
  { value: "hi-IN", label: "हिन्दी" },
  { value: "bn-IN", label: "বাংলা" },
  { value: "ta-IN", label: "தமிழ்" },
  { value: "te-IN", label: "తెలుగు" },
  { value: "kn-IN", label: "ಕನ್ನಡ" },
  { value: "ml-IN", label: "മലയാളം" },
  { value: "mr-IN", label: "मराठी" },
  { value: "gu-IN", label: "ગુજરાતી" },
  { value: "pa-IN", label: "ਪੰਜਾਬੀ" },
  { value: "od-IN", label: "ଓଡ଼ିଆ" },
  { value: "en-IN", label: "English" },
] as const;

export type RealtimeLanguage = "auto" | (typeof SPOKEN_LANGUAGES)[number]["value"];

export const LANGUAGE_OPTIONS: { value: RealtimeLanguage; label: string }[] = [
  { value: "auto", label: "Auto" },
  ...SPOKEN_LANGUAGES,
];

const LANGUAGE_KEY = "bb.agent.language.v1";

export function isRealtimeLanguage(value: unknown): value is RealtimeLanguage {
  return LANGUAGE_OPTIONS.some((l) => l.value === value);
}

export function loadLanguage(): RealtimeLanguage {
  try {
    const stored = window.localStorage.getItem(LANGUAGE_KEY);
    return isRealtimeLanguage(stored) ? stored : "auto";
  } catch {
    return "auto";
  }
}

export function saveLanguage(language: RealtimeLanguage): void {
  try {
    window.localStorage.setItem(LANGUAGE_KEY, language);
  } catch {
    // storage unavailable: the choice just is not remembered
  }
}
