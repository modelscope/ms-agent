/**
 * Remember the last non-settings route the user visited, so the Settings
 * page's Back button can return to it instead of walking the settings sub-nav
 * history one step at a time.
 *
 * Stored in sessionStorage (per-tab). Written by AppLayout on every location
 * change; read by SettingsLayout when Back is clicked.
 */

const KEY = "ms-agent-webui:last-app-route";

export function recordLastAppRoute(pathWithSearch: string): void {
  if (typeof sessionStorage === "undefined") return;
  // Don't record settings routes — that would defeat the purpose.
  if (pathWithSearch.startsWith("/settings")) return;
  try {
    sessionStorage.setItem(KEY, pathWithSearch);
  } catch {
    // sessionStorage can throw in private modes; nothing to do.
  }
}

export function getLastAppRoute(): string | null {
  if (typeof sessionStorage === "undefined") return null;
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}
