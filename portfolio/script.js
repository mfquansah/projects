const root = document.documentElement;
const saved = (() => { try { return localStorage.getItem('theme'); } catch { return null; } })();
const prefersDark = matchMedia('(prefers-color-scheme: dark)').matches;
root.dataset.theme = saved || (prefersDark ? 'dark' : 'light');

document.getElementById('theme-toggle').addEventListener('click', () => {
  const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
  root.dataset.theme = next;
  try { localStorage.setItem('theme', next); } catch {}
});
document.getElementById('year').textContent = new Date().getFullYear();

// Reveal the email address only on click, so it isn't in the page source for bots to scrape.
const emailBtn = document.getElementById('reveal-email');
if (emailBtn) {
  emailBtn.addEventListener('click', () => {
    const addr = ['mfquansah', 'gmail.com'].join('@');
    const link = document.createElement('a');
    link.className = 'pill';
    link.href = 'mailto:' + addr;
    link.append(emailBtn.querySelector('svg').cloneNode(true), addr);
    emailBtn.replaceWith(link);
    link.focus();
  });
}
