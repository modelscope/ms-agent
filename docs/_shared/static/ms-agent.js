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
    const expanded = !sidebar.classList.contains('-translate-x-full');
    menu.setAttribute('aria-expanded', String(expanded));
    if (!expanded && sidebar.contains(document.activeElement)) menu.focus();
  }).observe(sidebar, { attributes: true, attributeFilter: ['class'] });
  // Mermaid 扩展默认把图放大到整栏；保留原始图幅，窄屏仅缩小。
  const sizeDiagrams = () => {
    document.querySelectorAll('#content .mermaid svg').forEach((svg) => {
      const width = svg.viewBox?.baseVal?.width;
      if (width > 0) svg.style.width = `${width}px`;
    });
  };
  sizeDiagrams();
  const content = document.querySelector('#content');
  if (content) new MutationObserver(sizeDiagrams).observe(content, { childList: true, subtree: true });
});
