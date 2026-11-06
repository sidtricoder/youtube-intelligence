"""Modern, professional browser styling for approval and consent pages."""

CSS = """
:root {
  --bg: #0f1419;
  --surface: #1a2332;
  --surface-elevated: #243044;
  --text: #e8eef7;
  --text-muted: #9aa8bc;
  --accent: #3b82f6;
  --accent-hover: #2563eb;
  --success: #10b981;
  --danger: #ef4444;
  --border: #2d3a4f;
  --radius: 12px;
  --shadow: 0 4px 24px rgba(0, 0, 0, 0.25);
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color-scheme: dark;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg: #f8fafc;
    --surface: #ffffff;
    --surface-elevated: #f1f5f9;
    --text: #0f172a;
    --text-muted: #64748b;
    --border: #e2e8f0;
    --shadow: 0 4px 24px rgba(15, 23, 42, 0.08);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
}
main {
  max-width: 720px;
  margin: 2rem auto;
  padding: 0 1.25rem;
}
h1 {
  font-size: 1.75rem;
  font-weight: 650;
  letter-spacing: -0.02em;
  margin: 0 0 0.5rem;
}
h2 { font-size: 1.25rem; margin: 1.5rem 0 0.75rem; }
p { margin: 0.75rem 0; color: var(--text-muted); }
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.5rem;
  box-shadow: var(--shadow);
  margin: 1rem 0;
}
ol, ul { padding-left: 1.25rem; }
li { margin: 0.75rem 0; }
a {
  color: var(--accent);
  text-decoration: none;
  overflow-wrap: anywhere;
}
a:hover { text-decoration: underline; }
button, .btn {
  font: inherit;
  font-weight: 550;
  padding: 0.65rem 1.25rem;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  background: var(--accent);
  color: white;
  transition: background 0.15s ease, transform 0.1s ease;
}
button:hover, .btn:hover { background: var(--accent-hover); }
button:active { transform: scale(0.98); }
button:disabled { opacity: 0.6; cursor: wait; }
button.secondary {
  background: var(--surface-elevated);
  color: var(--text);
  border: 1px solid var(--border);
}
button.secondary:hover { background: var(--border); }
input {
  font: inherit;
  padding: 0.6rem 0.8rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  width: 100%;
  max-width: 280px;
}
code, pre {
  background: var(--surface-elevated);
  padding: 0.75rem 1rem;
  border-radius: 8px;
  font-size: 0.9rem;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  border: 1px solid var(--border);
}
details { margin: 1.5rem 0; }
summary { cursor: pointer; font-weight: 550; color: var(--text); }
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.meta {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
  font-size: 0.9rem;
  color: var(--text-muted);
  margin: 0.5rem 0 1rem;
}
.meta span { background: var(--surface-elevated); padding: 0.25rem 0.6rem; border-radius: 6px; }
#result { margin-top: 1rem; font-weight: 550; }
"""
