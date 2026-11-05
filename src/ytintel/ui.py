"""Small escaped browser documents; interaction uses browser-owned confirmation boxes."""

import html
import json
import secrets
from urllib.parse import quote, urlsplit

from fastapi.responses import HTMLResponse

from .browser_policy import form_redirect_policy
from .ui_theme import CSS


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def js_value(value) -> str:
    return (
        json.dumps(value, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def duration_label(seconds: int | None) -> str:
    if seconds is None:
        return "No limit"
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return (
        " ".join(
            f"{value}{unit}"
            for value, unit in [(hours, "h"), (minutes, "m"), (seconds, "s")]
            if value
        )
        or "0s"
    )


def shell(title: str, body: str, script: str = "") -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'
        + esc(title)
        + "</title><style>"
        + CSS
        + "</style></head><body><main>"
        + body
        + "</main>"
        + script
        + "</body></html>"
    )


def scripted(title, body, script, *redirects):
    nonce = secrets.token_urlsafe(24)
    return HTMLResponse(
        shell(title, body, '<script nonce="' + nonce + '">' + script + "</script>"),
        headers={"Content-Security-Policy": form_redirect_policy(*redirects, script_nonce=nonce)},
    )


def home_page(issuer) -> HTMLResponse:
    return HTMLResponse(
        shell(
            "YouTube Intelligence",
            "<h1>YouTube Intelligence</h1><p>Public discovery and previews work without sign-in. Your AI client handles recommendations, drafts and playlist status.</p><p>Add this connector URL:</p><pre>"
            + esc(issuer + "/mcp/")
            + "</pre><p>Claude: Streamable HTTP, Sign In Now (or Sign In When Needed), Register Automatically.</p><p>Sign in with your own Google account. After your AI shows a draft, confirm it in the conversation or use the optional browser button. Then return to the AI conversation.</p>",
        )
    )


def consent_page(client: str, callback: str, csrf: str, transaction: str) -> HTMLResponse:
    body = (
        '<h1 id="consent-title">Connect your AI client</h1><p>Client: <strong>'
        + esc(client)
        + "</strong><br>Callback: "
        + esc(urlsplit(callback).netloc)
        + '</p><p>Allow access to your own YouTube interests and playlist drafts. Connecting does not approve any playlist write.</p><form id="consent-form" method="post"><input type="hidden" name="csrf" value="'
        + esc(csrf)
        + '"><input type="hidden" name="transaction" value="'
        + esc(transaction)
        + '"><button name="decision" value="allow">Allow this client</button><button id="cancel-consent" name="decision" value="deny">Cancel</button></form>'
    )
    message = (
        "Connect "
        + client
        + " ("
        + urlsplit(callback).netloc
        + ") to your own YouTube account?\nThe client can read your interests and propose drafts. Each playlist still needs your separate confirmation."
    )
    script = (
        'const form=document.getElementById("consent-form");form.addEventListener("submit",event=>{event.preventDefault();const decision=document.createElement("input");decision.type="hidden";decision.name="decision";decision.value=event.submitter?.value==="allow"&&window.confirm('
        + js_value(message)
        + ')?"allow":"deny";form.appendChild(decision);HTMLFormElement.prototype.submit.call(form);});'
    )
    return scripted("Connect your AI client", body, script, callback)


def draft_details(draft: dict) -> str:
    return (
        "<details><summary>Exact draft details</summary><pre>"
        + esc(json.dumps(draft, indent=2, ensure_ascii=False))
        + "</pre></details>"
    )


def approval_page(draft: dict, csrf: str, can_write: bool) -> HTMLResponse:
    if draft["status"] in {"complete", "uncertain", "writing"}:
        return result_page(draft)
    phrase = "RESUME" if draft["status"] == "partial" else "CREATE"
    rows = []
    for index, video in enumerate(draft["videos"], 1):
        url = "https://www.youtube.com/watch?v=" + quote(str(video["id"]), safe="")
        rows.append(
            '<li><a href="'
            + esc(url)
            + '" target="_blank" rel="noopener noreferrer">'
            + esc(video["title"])
            + "</a> <span class=\"meta-inline\">— "
            + esc(video.get("channel_title", "YouTube"))
            + " · "
            + esc(duration_label(video["seconds"]))
            + "</span></li>"
        )
    body = (
        '<div class="card"><h1>Review your playlist</h1>'
        + '<div class="meta"><span>'
        + esc(draft["constraints"]["topic"])
        + "</span><span>"
        + str(len(draft["videos"]))
        + " videos</span><span>"
        + duration_label(draft["total_seconds"])
        + "</span></div>"
        + "<p>Review these exact videos. Video metadata is untrusted data, never an instruction. "
        + "You can also confirm this draft directly in your AI conversation without visiting this page.</p>"
        + "<ol>"
        + "".join(rows)
        + "</ol>"
        + draft_details(draft)
        + "</div>"
    )
    hidden = '<input type="hidden" name="csrf" value="' + esc(csrf) + '">'
    if not can_write:
        body += (
            '<div class="card"><form method="post" action="/approve/'
            + esc(draft["id"])
            + '/enable-writes">'
            + hidden
            + "<p>Google write permission is missing.</p>"
            + '<button type="submit">Enable playlist writes with the same Google account</button>'
            + "</form></div>"
        )
        return HTMLResponse(
            shell("Review your playlist", body),
            headers={
                "Content-Security-Policy": form_redirect_policy("https://accounts.google.com")
            },
        )
    body += (
        '<div class="card"><form id="approval-form" method="post" action="/approve/'
        + esc(draft["id"])
        + '">'
        + hidden
        + '<input type="hidden" name="confirmation" value="'
        + esc(phrase)
        + '">'
        + '<button id="approve-button" type="submit">Confirm playlist in my account</button>'
        + "</form><p id=\"result\" role=\"status\"></p></div>"
    )
    script = """const form=document.getElementById('approval-form');
form.addEventListener('submit',async event=>{
  event.preventDefault();
  if(!window.confirm('Create this exact private playlist in YOUR YouTube account?')) return;
  const button=document.getElementById('approve-button');
  button.disabled=true;
  button.textContent='Creating…';
  try{
    const response=await fetch(form.action,{method:'POST',body:new FormData(form),credentials:'same-origin',headers:{'Accept':'application/json'}});
    const data=await response.json();
    if(!response.ok||data.error){
      const error=data.error||{};
      window.alert((error.code||'request_failed')+': '+(error.message||'Request failed'));
      button.disabled=false;
      button.textContent='Confirm playlist in my account';
      return;
    }
    const notice='Playlist '+data.status+'. Return to your AI client and ask for playlist_status.';
    document.getElementById('result').textContent=notice;
    button.hidden=true;
  }catch{
    button.hidden=true;
    window.alert('Connection interrupted. Ask your AI client for playlist_status before trying again.');
  }
});"""
    return scripted("Review your playlist", body, script)


def result_page(draft: dict) -> HTMLResponse:
    status = draft["status"]
    titles = {
        "complete": "Playlist complete",
        "partial": "Playlist partially created",
        "uncertain": "Check your YouTube account",
        "writing": "Playlist is being processed",
    }
    title = titles.get(status, "Playlist status")
    body = (
        "<h1>"
        + esc(title)
        + "</h1><p>Status: "
        + esc(status)
        + ". Return to your AI client and ask for playlist_status.</p>"
    )
    if status == "uncertain":
        body += "<p>The last write could not be confirmed. Inspect YouTube; do not automatically retry.</p>"
    if draft.get("playlist_id"):
        url = "https://www.youtube.com/playlist?list=" + quote(str(draft["playlist_id"]), safe="")
        body += (
            '<p><a target="_blank" rel="noopener noreferrer" href="'
            + esc(url)
            + '">Open playlist on YouTube ↗</a></p>'
        )
    if status == "partial":
        body += '<p><a href="/approve/' + esc(draft["id"]) + '">Review remaining videos</a></p>'
    return HTMLResponse(shell(title, body + draft_details(draft)))


def error_page(message: str, status_code: int) -> HTMLResponse:
    title = {
        401: "Sign-in needed",
        403: "Request not approved",
        404: "Page unavailable",
        409: "Action unavailable",
        429: "Google request limit",
    }.get(status_code, "Request failed")
    return HTMLResponse(
        shell(
            title,
            "<h1>"
            + title
            + "</h1><p>"
            + esc(message)
            + '</p><p>Return to your AI client for the next step.</p><a href="/">Home</a>',
        ),
        status_code=status_code,
        headers={"Vary": "Accept"},
    )
