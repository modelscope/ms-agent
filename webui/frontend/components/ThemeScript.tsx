'use client';

/**
 * Theme initialization script component
 * Prevents flash of unstyled content (FOUC) by applying theme before hydration
 */
export default function ThemeScript() {
  // This script runs before hydration to prevent FOUC
  const themeScript = `
    (function() {
      try {
        const stored = localStorage.getItem('ms-agent-theme');
        if (stored === 'light' || stored === 'dark') {
          document.documentElement.classList.toggle('dark', stored === 'dark');
          return;
        }
        
        const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        document.documentElement.classList.toggle('dark', systemTheme === 'dark');
        localStorage.setItem('ms-agent-theme', systemTheme);
      } catch (e) {}
    })();
  `;
  
  return (
    <script
      dangerouslySetInnerHTML={{ __html: themeScript }}
      suppressHydrationWarning
    />
  );
}
