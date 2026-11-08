"""Modern, professional browser styling for approval and consent pages."""

CSS = """
:root {
  --bg: #080c14;
  --bg-pattern: radial-gradient(ellipse 80% 50% at 50% -10%, rgba(59,130,246,0.12) 0%, transparent 70%);
  --surface: #111827;
  --surface-elevated: #1e2d3d;
  --surface-hover: #243347;
  --text: #f0f4fc;
  --text-muted: #8b9cb8;
  --text-subtle: #4a5568;
  --accent: #3b82f6;
  --accent-hover: #2563eb;
  --accent-glow: rgba(59,130,246,0.25);
  --accent-dim: rgba(59,130,246,0.15);
  --success: #10b981;
  --success-dim: rgba(16,185,129,0.15);
  --danger: #f87171;
  --danger-dim: rgba(248,113,113,0.15);
  --warning: #f59e0b;
  --border: #1e2d3d;
  --border-subtle: #162030;
  --radius: 14px;
  --radius-sm: 8px;
  --shadow: 0 4px 32px rgba(0,0,0,0.5), 0 1px 0 rgba(255,255,255,0.03);
  --shadow-sm: 0 2px 8px rgba(0,0,0,0.3);
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color-scheme: dark;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg: #f0f4fc;
    --bg-pattern: radial-gradient(ellipse 80% 50% at 50% -10%, rgba(59,130,246,0.08) 0%, transparent 70%);
    --surface: #ffffff;
    --surface-elevated: #f4f7fc;
    --surface-hover: #eaf0fb;
    --text: #0d1b2e;
    --text-muted: #4a5a72;
    --text-subtle: #9ba8bb;
    --border: #dde5f0;
    --border-subtle: #e8eef8;
    --accent-dim: rgba(59,130,246,0.1);
    --shadow: 0 4px 24px rgba(15,23,42,0.1), 0 1px 0 rgba(0,0,0,0.04);
    --shadow-sm: 0 2px 8px rgba(15,23,42,0.08);
  }
}

/* ── Reset & base ──────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  min-height: 100vh;
  background: var(--bg);
  background-image: var(--bg-pattern);
  color: var(--text);
  line-height: 1.65;
  -webkit-font-smoothing: antialiased;
}

/* ── Layout ────────────────────────────────────── */
main {
  max-width: 700px;
  margin: 0 auto;
  padding: 2.5rem 1.5rem 4rem;
}

/* ── Typography ────────────────────────────────── */
h1 {
  font-size: 1.9rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.2;
  margin: 0 0 0.6rem;
  color: var(--text);
}
h2 {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 1.5rem 0 0.6rem;
  color: var(--text);
  letter-spacing: -0.01em;
}
p { margin: 0.7rem 0; color: var(--text-muted); font-size: 0.95rem; }
strong { color: var(--text); font-weight: 600; }

/* ── Cards ─────────────────────────────────────── */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.75rem;
  box-shadow: var(--shadow);
  margin: 1rem 0;
  position: relative;
  overflow: hidden;
}
.card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent);
}

/* ── Badge-style meta row ───────────────────────── */
.meta {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  font-size: 0.82rem;
  margin: 0.75rem 0 1.25rem;
}
.meta span {
  background: var(--accent-dim);
  color: var(--accent);
  padding: 0.25rem 0.65rem;
  border-radius: 100px;
  font-weight: 500;
  letter-spacing: 0.01em;
  border: 1px solid rgba(59,130,246,0.2);
}

/* ── Video list ─────────────────────────────────── */
ol {
  list-style: none;
  padding: 0;
  margin: 0.5rem 0;
  counter-reset: video-counter;
}
ol li {
  counter-increment: video-counter;
  display: flex;
  align-items: flex-start;
  gap: 0.85rem;
  padding: 0.9rem 0.5rem;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 0.93rem;
  line-height: 1.45;
  transition: background 0.12s ease;
}
ol li:last-child { border-bottom: none; }
ol li:hover { background: var(--surface-hover); border-radius: var(--radius-sm); }
ol li::before {
  content: counter(video-counter);
  flex-shrink: 0;
  width: 1.6rem;
  height: 1.6rem;
  background: var(--surface-elevated);
  border: 1px solid var(--border);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-muted);
  margin-top: 0.1rem;
}
ol li a {
  font-weight: 500;
  color: var(--text);
  flex: 1;
}
ol li a:hover { color: var(--accent); text-decoration: none; }
ul { list-style: none; padding: 0; }
ul li { padding: 0.4rem 0; }

/* ── Inline meta ────────────────────────────────── */
.meta-inline {
  display: block;
  font-size: 0.8rem;
  color: var(--text-muted);
  margin-top: 0.1rem;
}

/* ── Links ──────────────────────────────────────── */
a {
  color: var(--accent);
  text-decoration: none;
  overflow-wrap: anywhere;
}
a:hover { text-decoration: underline; }

/* ── Buttons ────────────────────────────────────── */
.btn-row {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-top: 1.25rem;
}
button, .btn {
  font: inherit;
  font-weight: 600;
  font-size: 0.95rem;
  padding: 0.7rem 1.4rem;
  border-radius: var(--radius-sm);
  border: none;
  cursor: pointer;
  background: var(--accent);
  color: white;
  transition: background 0.15s ease, transform 0.1s ease, box-shadow 0.15s ease;
  box-shadow: 0 0 0 0 var(--accent-glow);
  letter-spacing: 0.01em;
}
button:hover, .btn:hover {
  background: var(--accent-hover);
  box-shadow: 0 0 0 4px var(--accent-glow);
}
button:active { transform: scale(0.97); }
button:disabled { opacity: 0.5; cursor: wait; box-shadow: none; }
button.secondary {
  background: var(--surface-elevated);
  color: var(--text);
  border: 1px solid var(--border);
  box-shadow: none;
}
button.secondary:hover { background: var(--surface-hover); box-shadow: none; }
button.danger {
  background: var(--danger-dim);
  color: var(--danger);
  border: 1px solid rgba(248,113,113,0.25);
  box-shadow: none;
}
button.danger:hover { background: rgba(248,113,113,0.25); box-shadow: none; }

/* ── Form inputs ────────────────────────────────── */
input {
  font: inherit;
  padding: 0.65rem 0.9rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-elevated);
  color: var(--text);
  width: 100%;
  max-width: 320px;
  transition: border-color 0.15s;
}
input:focus { outline: none; border-color: var(--accent); }

/* ── Code / pre ─────────────────────────────────── */
code, pre {
  font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", ui-monospace, monospace;
  background: var(--surface-elevated);
  padding: 0.85rem 1.1rem;
  border-radius: var(--radius-sm);
  font-size: 0.875rem;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  border: 1px solid var(--border);
  color: var(--text);
  display: block;
  margin: 0.75rem 0;
  position: relative;
}

/* ── Details / summary ──────────────────────────── */
details {
  margin: 1.25rem 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
summary {
  cursor: pointer;
  font-weight: 500;
  font-size: 0.88rem;
  color: var(--text-muted);
  padding: 0.65rem 1rem;
  background: var(--surface-elevated);
  user-select: none;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
summary::before {
  content: '▶';
  font-size: 0.65rem;
  transition: transform 0.2s;
  opacity: 0.6;
}
details[open] summary::before { transform: rotate(90deg); }
details pre { margin: 0; border-radius: 0; border: none; border-top: 1px solid var(--border); font-size: 0.8rem; }

/* ── Status / result notice ─────────────────────── */
#result {
  margin-top: 1rem;
  font-weight: 600;
  font-size: 0.95rem;
  color: var(--success);
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
#result:not(:empty)::before { content: '✓'; }

/* ── Warning banner ─────────────────────────────── */
.warning-banner {
  background: rgba(245,158,11,0.1);
  border: 1px solid rgba(245,158,11,0.25);
  border-radius: var(--radius-sm);
  padding: 0.75rem 1rem;
  font-size: 0.88rem;
  color: var(--warning);
  margin: 0.75rem 0;
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
}
.warning-banner::before { content: '⚠'; flex-shrink: 0; }

/* ── Step list (home page) ──────────────────────── */
.steps {
  list-style: none;
  padding: 0;
  margin: 1.25rem 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.steps li {
  display: flex;
  align-items: flex-start;
  gap: 0.85rem;
  padding: 0.85rem 1rem;
  background: var(--surface-elevated);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
  font-size: 0.93rem;
  color: var(--text-muted);
}
.steps li .step-num {
  flex-shrink: 0;
  width: 1.6rem;
  height: 1.6rem;
  background: var(--accent-dim);
  border: 1px solid rgba(59,130,246,0.25);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--accent);
}
.steps li strong { display: block; color: var(--text); font-size: 0.93rem; margin-bottom: 0.1rem; }

/* ── Focus / a11y ───────────────────────────────── */
hr {
  border: none;
  border-top: 1px solid var(--border);
  margin: 1.25rem 0;
}

/* ── Focus / a11y ───────────────────────────────── */
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
  border-radius: 4px;
}
"""
