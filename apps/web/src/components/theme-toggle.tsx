"use client";

import { useEffect, useSyncExternalStore } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

type Theme = "light" | "dark" | "system";

const storageKey = "episignal-theme";
const OPTIONS = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
  { value: "system", label: "System", Icon: Monitor },
] as const;

// Falls back to module state when storage is unavailable (private mode, blocked cookies).
let volatilePreference: Theme = "system";

function readPreference(): Theme {
  try {
    const value = localStorage.getItem(storageKey);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return volatilePreference;
  }
}

function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener("episignal-theme", callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener("episignal-theme", callback);
  };
}

function applyTheme(
  preference: Theme,
  systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches,
) {
  const theme =
    preference === "system" ? (systemDark ? "dark" : "light") : preference;
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}

function selectTheme(next: Theme) {
  volatilePreference = next;
  applyTheme(next);
  try {
    localStorage.setItem(storageKey, next);
  } catch {
    /* Preference still applies for this session. */
  }
  window.dispatchEvent(new Event("episignal-theme"));
}

export const themeScript = `(function(){var t='system';try{t=localStorage.getItem('episignal-theme')||t}catch(e){}var d=t==='dark'||(t!=='light'&&matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.dataset.theme=d?'dark':'light';document.documentElement.style.colorScheme=d?'dark':'light'})()`;

export function ThemeToggle() {
  const preference = useSyncExternalStore(
    subscribe,
    readPreference,
    () => "system" as Theme,
  );

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => applyTheme(preference, media.matches);
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [preference]);

  return (
    <div className="theme-control" role="group" aria-label="Theme">
      {OPTIONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          className="theme-control__option"
          aria-pressed={preference === value}
          aria-label={`${label} theme`}
          title={`${label} theme`}
          onClick={() => selectTheme(value)}
        >
          <Icon size={16} strokeWidth={1.75} aria-hidden="true" />
        </button>
      ))}
    </div>
  );
}
