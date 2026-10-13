'use strict';
// Loaded synchronously in <head> so a stored theme applies before first paint.
(function () {
  const root = document.documentElement;
  const KEY = 'aspire-theme';
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  let stored = null;
  try {stored = localStorage.getItem(KEY);} catch (error) {stored = null;}
  if (stored === 'light' || stored === 'dark') root.dataset.theme = stored;
  const current = () => root.dataset.theme || (media.matches ? 'dark' : 'light');
  function sync(button) {
    const dark = current() === 'dark';
    button.setAttribute('aria-pressed', String(dark));
    button.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
    button.title = dark ? 'Switch to light theme' : 'Switch to dark theme';
  }
  document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('theme-toggle');
    if (!button) return;
    sync(button);
    button.hidden = false;
    button.addEventListener('click', () => {
      root.dataset.theme = current() === 'dark' ? 'light' : 'dark';
      try {localStorage.setItem(KEY, root.dataset.theme);} catch (error) { /* preference is optional */ }
      sync(button);
    });
    media.addEventListener('change', () => sync(button));
  });
})();
