"""Self-contained presentation styles; no third-party fonts, assets or tracking."""

CSS = """
:root{color-scheme:light;--ink:#18302f;--muted:#5b706b;--paper:#fffefa;--line:#dde7df;
--accent:#126458;--soft:#edf5ef;--warm:#f6f5ef;--danger:#9a4336}
*{box-sizing:border-box}body{margin:0;background:var(--warm);color:var(--ink);
font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
font-size:15px;line-height:1.65}a{color:var(--accent);text-underline-offset:4px}
button,input,a{ -webkit-tap-highlight-color:transparent}button,input{font:inherit}
button,a,input,summary{outline-offset:5px}button:focus-visible,a:focus-visible,input:focus-visible,
summary:focus-visible{outline:3px solid #c27b39}button{cursor:pointer}a.brand{text-decoration:none}
.topbar{max-width:1120px;margin:auto;padding:28px 32px;display:flex;align-items:center;
justify-content:space-between;gap:20px}.brand{display:flex;align-items:center;gap:10px;color:var(--ink);
font-weight:760;letter-spacing:-.7px;font-size:21px}.mark{display:grid;place-items:center;width:34px;
height:34px;background:var(--accent);color:white;border-radius:10px;font-size:15px}
.tag,.eyebrow{text-transform:uppercase;letter-spacing:1.8px;font-weight:750;font-size:10px}
.tag{color:var(--muted)}.eyebrow{color:var(--accent);margin-bottom:14px}main{max-width:1060px;
margin:34px auto 60px;padding:0 32px}h1,h2,h3,p{margin-top:0}h1{font-size:clamp(32px,5vw,58px);
letter-spacing:-2px;line-height:1.12;margin-bottom:22px;font-weight:650}h2{font-size:24px;
line-height:1.25;letter-spacing:-.7px}h3{font-size:17px;line-height:1.4;margin-bottom:5px}
.lead{font-size:17px;color:var(--muted);max-width:580px}.muted{color:var(--muted)}
.hero{display:grid;grid-template-columns:1.15fr 1fr;gap:64px;align-items:center;padding:24px 0 48px}
.card{background:var(--paper);border:1px solid var(--line);border-radius:22px;padding:28px}
.steps{display:grid;gap:22px}.step{display:flex;gap:18px}.number{font-size:12px;color:var(--accent);
font-weight:750;background:var(--soft);width:30px;height:30px;border-radius:50%;display:grid;
place-items:center;flex-shrink:0}.step p{margin:0;color:var(--muted);font-size:13px}
.endpoint{display:block;background:var(--soft);border:1px solid var(--line);padding:17px 20px;
border-radius:12px;overflow-wrap:anywhere;font-size:13px;margin:18px 0 12px}.fine{font-size:12px;
color:var(--muted)}.footer{max-width:1120px;margin:auto;padding:22px 32px;border-top:1px solid
var(--line);display:flex;justify-content:space-between;gap:16px;font-size:12px;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.badge{display:inline-flex;gap:7px;
align-items:center;border-radius:50px;background:var(--soft);padding:6px 11px;font-size:11px;
font-weight:650;color:var(--accent)}.dot{width:6px;height:6px;background:var(--accent);border-radius:50%}
.center{max-width:680px;margin:52px auto}.center h1{font-size:38px;letter-spacing:-1px}
.actions{display:flex;align-items:center;gap:12px;margin-top:24px;flex-wrap:wrap}.button,button{
display:inline-flex;justify-content:center;align-items:center;min-height:46px;border:1px solid
var(--accent);border-radius:10px;padding:11px 20px;background:var(--accent);color:white;
font-weight:650;font-size:13px;text-decoration:none}.secondary{background:transparent;
color:var(--ink);border-color:var(--line)}.button:hover,button:hover{filter:brightness(.96)}
.dialog-stage{min-height:64vh;display:grid;place-items:center}.dialog-underlay{text-align:center;
color:var(--muted);max-width:380px}.dialog-underlay h1{font-size:32px;letter-spacing:-1px}
dialog{border:1px solid var(--line);padding:0;border-radius:24px;width:min(520px,calc(100% - 32px));
max-height:calc(100dvh - 48px);overflow:auto;background:var(--paper);color:var(--ink);
box-shadow:0 28px 100px #142f3133}dialog::backdrop{background:#16312c70;backdrop-filter:blur(6px)}
.dialog-inner{padding:32px}.dialog-top{display:flex;justify-content:space-between;align-items:center;
margin-bottom:24px}.close{border:0;background:transparent;color:var(--muted);font-size:24px;
min-height:32px;padding:0 5px}.dialog-inner h1{font-size:30px;letter-spacing:-1px;margin:14px 0}
.client{display:flex;align-items:center;gap:12px;padding:14px;background:var(--soft);
border-radius:12px;margin:22px 0}.client-symbol{background:var(--paper);padding:8px;border-radius:9px}
.client strong{display:block;overflow-wrap:anywhere}.client small{display:block;color:var(--muted);
font-size:11px;overflow-wrap:anywhere}.permission{display:flex;gap:12px;padding:16px 0;border-bottom:
1px solid var(--line)}.permission-icon{font-size:18px;color:var(--accent)}.permission p{font-size:12px;
color:var(--muted);margin:2px 0 0}.note{background:var(--soft);padding:14px 16px;border-radius:12px;
font-size:12px;color:var(--muted);margin:22px 0}.dialog-actions{display:flex;gap:12px;justify-content:
flex-end;margin-top:24px}.dialog-actions button{flex:1}.review-header{display:flex;justify-content:
space-between;gap:20px;align-items:center;margin-bottom:26px}.review-header h1{font-size:38px;
letter-spacing:-1px;margin:8px 0 12px}.stats{display:grid;grid-template-columns:repeat(3,1fr);
border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin:25px 0;padding:20px 0}
.stats strong,.stats span{display:block}.stats strong{font-size:20px}.stats span{font-size:11px;
color:var(--muted)}.videos{list-style:none;padding:0;margin:0}.video{display:flex;gap:16px;padding:
20px 0;border-bottom:1px solid var(--line)}.video-number{color:var(--muted);font-size:12px;width:22px;
flex-shrink:0;margin-top:3px}.video-body{flex:1;min-width:0}.video h3 a{color:var(--ink);
text-decoration:none}.video p{font-size:12px;color:var(--muted);margin:4px 0}.duration{font-size:12px;
color:var(--accent);white-space:nowrap;align-self:center}.review-grid{display:grid;grid-template-columns:
1.55fr 1fr;gap:28px;align-items:start}.confirmation{position:sticky;top:24px}.confirmation label{
display:block;font-size:13px;margin:18px 0 9px}.confirmation input{width:100%;min-height:48px;
border:1px solid #a9beb1;border-radius:9px;padding:10px 13px;background:var(--paper);color:var(--ink)}
.confirmation button{width:100%;margin-top:14px}.confirmation p{font-size:13px;color:var(--muted)}
details{margin-top:24px;color:var(--muted);font-size:12px}summary{cursor:pointer}pre{white-space:
pre-wrap;overflow-wrap:anywhere;background:var(--soft);padding:18px;border-radius:12px;font-size:11px;
max-height:380px;overflow:auto}code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.result-icon{font-size:28px;display:grid;place-items:center;border-radius:50%;width:62px;height:62px;
background:var(--soft);color:var(--accent);margin-bottom:24px}.warning{color:var(--danger)}
@media(max-width:720px){.topbar{padding:20px}.tag{display:none}main{margin:20px auto 40px;
padding:0 20px}.hero,.review-grid{grid-template-columns:1fr;gap:24px}.hero{padding:12px 0 24px}
.grid{grid-template-columns:1fr}.card{padding:22px}.dialog-inner{padding:20px;line-height:1.5}.dialog-inner h1{font-size:28px}.dialog-inner .permission{padding:12px 0}.dialog-inner .note{margin:16px 0;padding:12px}.dialog-inner .client{margin:16px 0}.dialog-actions{margin-top:18px}.dialog-actions button{padding:11px 12px;font-size:12px}.footer{padding:20px;
flex-direction:column;gap:5px}.confirmation{position:static}.review-header{display:block}
.review-header h1{font-size:32px}.stats strong{font-size:17px}.video{gap:10px}.duration{align-self:
flex-start;margin-top:3px}.video h3{font-size:14px}.center{margin:30px auto}.center h1{font-size:30px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
"""
