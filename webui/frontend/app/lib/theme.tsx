import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export type Theme = "light" | "dark";

export const THEME_COOKIE = "ms-agent-webui:theme";
const COOKIE_MAX_AGE = 60 * 60 * 24 * 365; // 1 year

interface ThemeContextValue {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function writeCookie(theme: Theme) {
  if (typeof document === "undefined") return;
  document.cookie = `${THEME_COOKIE}=${theme}; path=/; max-age=${COOKIE_MAX_AGE}; SameSite=Lax`;
}

export function ThemeProvider({
  initialTheme = "light",
  children,
}: {
  initialTheme?: Theme;
  children: React.ReactNode;
}) {
  // Initial state must equal what the server rendered, otherwise antd's cssinjs
  // emits different class names per theme and hydration mismatches.
  const [theme, setThemeState] = useState<Theme>(initialTheme);

  // First-time visitors arrive without a cookie. If they prefer dark via OS,
  // upgrade once and persist. (Causes a one-shot light→dark flash on the very
  // first visit only — every subsequent visit reads the cookie and matches.)
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (document.cookie.includes(`${THEME_COOKIE}=`)) return;
    if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
      setThemeState("dark");
      writeCookie("dark");
    }
  }, []);

  // Keep the <html> class in sync — needed both for the OS-pref upgrade above
  // and any user toggle. The server-rendered class is set in root.tsx Layout.
  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    writeCookie(next);
  }, []);

  const toggleTheme = useCallback(
    () => setTheme(theme === "dark" ? "light" : "dark"),
    [setTheme, theme],
  );

  const value = useMemo(
    () => ({ theme, setTheme, toggleTheme }),
    [theme, setTheme, toggleTheme],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}
