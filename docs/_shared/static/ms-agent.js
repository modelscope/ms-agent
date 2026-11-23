// 为默认移动导航补充可访问名称，保持主题的交互与持久化行为。
document.addEventListener('DOMContentLoaded', () => {
  const zh = document.documentElement.lang.startsWith('zh');
  const search = document.querySelector('#search-input');
  if (search) {
    search.placeholder = zh ? '搜索文档…' : 'Search docs…';
    search.setAttribute('aria-label', zh ? '搜索文档' : 'Search the docs');
  }
  const toggle = document.querySelector('header button[title="Toggle color scheme"]');
  if (toggle) toggle.setAttribute('aria-label', zh ? '切换明暗主题' : 'Toggle color scheme');
  const menu = document.querySelector('header button[type="button"]');
  if (menu && menu !== toggle) {
    menu.setAttribute('aria-label', zh ? '打开导航' : 'Open navigation');
    menu.setAttribute('aria-controls', 'left-sidebar');
    menu.setAttribute('aria-expanded', 'false');
    menu.addEventListener('click', () => menu.setAttribute('aria-expanded', 'true'));
  }
  const close = document.querySelector('#left-sidebar button');
  if (close) {
    close.setAttribute('aria-label', zh ? '关闭导航' : 'Close navigation');
    close.addEventListener('click', () => {
      menu?.setAttribute('aria-expanded', 'false');
      menu?.focus();
    });
  }
  const sidebar = document.querySelector('#left-sidebar');
  if (sidebar && menu) new MutationObserver(() => {
    const expanded = sidebar.classList.contains('translate-x-0');
    menu.setAttribute('aria-expanded', String(expanded));
    if (!expanded && sidebar.contains(document.activeElement)) menu.focus();
  }).observe(sidebar, { attributes: true, attributeFilter: ['class'] });
  let fullscreenTrigger = null;
  const restoreFullscreenFocus = () => requestAnimationFrame(() => fullscreenTrigger?.focus());
  document.addEventListener('click', (event) => {
    const button = event.target.closest('.mermaid-fullscreen-btn');
    if (button) fullscreenTrigger = button;
    if (event.target.closest('.mermaid-fullscreen-close') ||
        event.target.classList.contains('mermaid-fullscreen-modal')) restoreFullscreenFocus();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') restoreFullscreenFocus();
  });
  // Mermaid 按当前页面主题渲染，不让系统暗色偏好覆盖用户选择的浅色。
  const syncTheme = () => document.documentElement.setAttribute('data-theme',
    document.documentElement.classList.contains('dark') ? 'dark' : 'light');
  syncTheme();
  new MutationObserver(syncTheme).observe(document.documentElement,
    { attributes: true, attributeFilter: ['class'] });
  // 搜索摘要提取的是未执行脚本的 HTML；去掉图表源码而保留正文。
  if (typeof Search !== 'undefined' && Search.htmlToText) {
    const original = Search.htmlToText;
    Search.htmlToText = (html, anchor) => {
      const doc = new DOMParser().parseFromString(html, 'text/html');
      doc.querySelectorAll('.mermaid, .no-search').forEach((node) => node.remove());
      return original(doc.documentElement.outerHTML, anchor);
    };
  }
  // 保留原始图幅；窄屏在图表容器内横向滚动，不缩小文字。
  const sizeDiagrams = () => {
    document.querySelectorAll('#content .mermaid svg').forEach((svg) => {
      const width = svg.viewBox?.baseVal?.width;
      if (width > 0) svg.style.width = `${width}px`;
      const container = svg.closest('.mermaid');
      if (container) {
        container.setAttribute('tabindex', '0');
        container.setAttribute('role', 'region');
        container.setAttribute('aria-label', zh ? '图表，可横向滚动' : 'Diagram, scroll horizontally');
      }
    });
  };
  sizeDiagrams();
  const content = document.querySelector('#content');
  if (content) new MutationObserver(sizeDiagrams).observe(content, { childList: true, subtree: true });
});
