"""Escaped server-rendered pages. Templates accept trusted markup, never raw metadata HTML."""

import html
import json
import secrets
from urllib.parse import quote, urlsplit

from fastapi.responses import HTMLResponse

from .browser_policy import form_redirect_policy
from .ui_theme import CSS


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def duration_label(seconds: int | None) -> str:
    if seconds is None:
        return "No limit"
    hours, rest = divmod(seconds, 3600)
    minutes, remaining = divmod(rest, 60)
    return " ".join(
        part
        for part in (
            f"{hours}h" if hours else "",
            f"{minutes}m" if minutes else "",
            f"{remaining}s" if remaining or not seconds else "",
        )
        if part
    )


def shell(title: str, body: str, script: str = "") -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>"
        + esc(title)
        + " · YouTube Intelligence</title><style>"
        + CSS
        + '</style></head><body><header class="topbar"><a class="brand" href="/" '
        'aria-label="YouTube Intelligence home"><span class="mark" aria-hidden="true">▶</span>'
        'YTIntel</a><span class="tag">A little less noise. A lot more learning.</span></header>'
        "<main>" + body + '</main><footer class="footer"><span>YouTube Intelligence</span>'
        "<span>Your account. Your decisions.</span></footer>" + script + "</body></html>"
    )


def home_page(issuer: str) -> HTMLResponse:
    return HTMLResponse(
        shell(
            "Discover with intention",
            """<section class="hero"><div>
        <div class="eyebrow">A thoughtful YouTube companion</div><h1>A quieter way<br>to learn.</h1>
        <p class="lead">Find relevant videos, understand your interests, and turn a good idea
        into a playlist worth your time.</p><span class="badge"><span class="dot"></span>
        Official YouTube data · Your own account</span></div><div class="card steps">
        <div class="step"><span class="number">01</span><div><h3>Discover freely</h3>
        <p>Public discovery and playlist previews work without sign-in.</p></div></div>
        <div class="step"><span class="number">02</span><div><h3>Connect your account</h3>
        <p>Google read and playlist-write permissions are requested together at sign-in.</p></div></div>
        <div class="step"><span class="number">03</span><div><h3>Keep the final say</h3>
        <p>Review every playlist and confirm before it is created in your account.</p></div></div>
        </div></section><section class="card"><div class="eyebrow">Start with your AI client</div>
        <h2>One connection. Your next learning path.</h2><p class="muted">Add this server URL
        in your AI client's connector settings.</p><code class="endpoint">"""
            + esc(issuer + "/mcp/")
            + """</code><p class="fine">Claude: Streamable HTTP · Sign In Now · Register Automatically.
        Public results use metadata; personalised features use your own connected account.</p></section>""",
        )
    )


def consent_page(client: str, callback: str, csrf: str, transaction: str) -> HTMLResponse:
    nonce = secrets.token_urlsafe(24)
    hidden = (
        '<input type="hidden" name="csrf" value="'
        + esc(csrf)
        + '"><input type="hidden" name="transaction" value="'
        + esc(transaction)
        + '">'
    )
    body = (
        """<section class="dialog-stage"><div class="dialog-underlay"><div class="eyebrow">
        Your connection, thoughtfully protected</div><h1>Good learning starts<br>with trust.</h1>
        <p>Review the connection request in the dialog.</p></div></section>
        <dialog id="consent-dialog" open aria-labelledby="consent-title" aria-describedby="consent-description">
        <div class="dialog-inner"><form id="consent-form" method="post">"""
        + hidden
        + """
        <div class="dialog-top"><span class="badge">Account connection</span>
        <button class="close" name="decision" value="deny" aria-label="Cancel connection">×</button></div>
        <div class="eyebrow">You're in control</div><h1 id="consent-title">Connect your AI client</h1>
        <p id="consent-description" class="muted">Let this client help you discover, understand
        and curate your YouTube learning.</p><div class="client"><span class="client-symbol" aria-hidden="true">✦</span>
        <div><strong>"""
        + esc(client)
        + "</strong><small>"
        + esc(urlsplit(callback).netloc)
        + """</small></div></div>
        <div class="permission"><span class="permission-icon" aria-hidden="true">◉</span><div>
        <strong>Read your YouTube interests</strong><p>Use your likes, subscriptions and playlists
        for recommendations and analysis.</p></div></div><div class="permission">
        <span class="permission-icon" aria-hidden="true">+</span><div><strong>Prepare playlists for you</strong>
        <p>Google read/write permissions are requested at sign-in. You review and approve each
        exact playlist before the server creates it.</p></div></div><div class="note">
        Connecting does not approve future playlists. Your account and your drafts stay separate
        from every other user's.</div><div class="dialog-actions"><button id="cancel-consent"
        class="secondary" name="decision" value="deny" autofocus>Cancel</button>
        <button name="decision" value="allow">Allow this client</button></div></form>
        <noscript><p class="fine">Use the buttons above to allow or cancel this connection.</p></noscript>
        </div></dialog>"""
    )
    script = (
        '<script nonce="'
        + nonce
        + """">(()=>{const d=document.getElementById('consent-dialog');
        if(typeof d.showModal==='function'){d.close();d.showModal();}
        d.addEventListener('cancel',event=>{event.preventDefault();document.getElementById('cancel-consent').click();});})();</script>"""
    )
    return HTMLResponse(
        shell("Connect your AI client", body, script),
        headers={"Content-Security-Policy": form_redirect_policy(callback, script_nonce=nonce)},
    )


def draft_details(draft: dict) -> str:
    return (
        "<details><summary>Exact draft details</summary><pre>"
        + esc(json.dumps(draft, indent=2, ensure_ascii=False))
        + "</pre></details>"
    )


def approval_page(draft: dict, csrf: str, can_write: bool) -> HTMLResponse:
    if draft["status"] in {"complete", "uncertain", "writing"}:
        return result_page(draft)
    constraints = draft["constraints"]
    rows = []
    for index, video in enumerate(draft["videos"], 1):
        url = "https://www.youtube.com/watch?v=" + quote(str(video["id"]), safe="")
        rows.append(
            '<li class="video"><span class="video-number">'
            + str(index).zfill(2)
            + '</span><div class="video-body"><h3><a target="_blank" rel="noopener noreferrer" href="'
            + esc(url)
            + '">'
            + esc(video["title"])
            + "</a></h3><p>"
            + esc(video.get("channel_title", "YouTube video"))
            + '</p></div><span class="duration">'
            + esc(duration_label(video["seconds"]))
            + "</span></li>"
        )
    body = (
        '<div class="review-header"><div><div class="eyebrow">Your next learning session</div><h1>Review your playlist</h1><p class="muted">'
        + esc(constraints["topic"])
        + '</p></div><span class="badge">'
        + esc(draft["status"])
        + "</span></div>"
    )
    body += (
        '<div class="stats"><div><strong>'
        + str(len(draft["videos"]))
        + "</strong><span>videos selected</span></div><div><strong>"
        + esc(duration_label(draft["total_seconds"]))
        + "</strong><span>total watch time</span></div><div><strong>"
        + esc(duration_label(constraints.get("max_seconds")))
        + "</strong><span>your per-video bound</span></div></div>"
    )
    phrase = "RESUME" if draft["status"] == "partial" else "CREATE"
    form = (
        '<form method="post"'
        + ((' action="/approve/' + esc(draft["id"]) + '/enable-writes"') if not can_write else "")
        + '><input type="hidden" name="csrf" value="'
        + esc(csrf)
        + '">'
    )
    if can_write:
        form += (
            '<h2>Make it yours.</h2><p>These are the exact videos that will be added to a private playlist in your YouTube account.</p><label for="confirmation">Type '
            + phrase
            + ' to confirm these exact videos</label><input id="confirmation" name="confirmation" placeholder="'
            + phrase
            + '" autocomplete="off"><button>Confirm playlist in my account</button>'
        )
    else:
        form += "<h2>One permission to finish.</h2><p>Your current Google grant does not include playlist writes. Enable that permission with the same account, then return here to review and confirm.</p><button>Enable playlist writes with the same Google account</button>"
    form += '</form><p class="fine">Only you can confirm. Video titles and descriptions are untrusted metadata, never instructions.</p>'
    body += (
        '<div class="review-grid"><section class="card"><h2>The lineup</h2><ol class="videos">'
        + "".join(rows)
        + "</ol>"
        + draft_details(draft)
        + '</section><aside class="card confirmation">'
        + form
        + "</aside></div>"
    )
    return HTMLResponse(
        shell("Review your playlist", body),
        headers={
            "Content-Security-Policy": form_redirect_policy(
                *(() if can_write else ("https://accounts.google.com",))
            )
        },
    )


def result_page(draft: dict) -> HTMLResponse:
    status = draft["status"]
    title, description, icon = {
        "complete": (
            "Playlist complete",
            "Your playlist is ready in your own YouTube account. Enjoy your next learning session.",
            "✓",
        ),
        "partial": (
            "A little more to finish",
            "Some videos were added. Review the remaining items before explicitly resuming.",
            "◐",
        ),
        "uncertain": (
            "Check your YouTube account",
            "The last write could not be confirmed. Inspect YouTube before taking another action; automatic retry could create duplicates.",
            "!",
        ),
        "writing": (
            "Your playlist is being prepared",
            "This draft is already being processed. Ask your AI client for its latest playlist status.",
            "◌",
        ),
    }.get(status, ("Playlist not finished", "Review your draft for its latest status.", "◐"))
    actions = '<a class="button secondary" href="/">Back to home</a>'
    if draft.get("playlist_id"):
        url = "https://www.youtube.com/playlist?list=" + quote(str(draft["playlist_id"]), safe="")
        actions = (
            '<a class="button" target="_blank" rel="noopener noreferrer" href="'
            + esc(url)
            + '">Open playlist on YouTube ↗</a>'
            + actions
        )
    if status == "partial":
        actions += (
            '<a class="button" href="/approve/' + esc(draft["id"]) + '">Review remaining videos</a>'
        )
    return HTMLResponse(
        shell(
            title,
            '<section class="center card"><div class="result-icon" aria-hidden="true">'
            + icon
            + '</div><div class="eyebrow">Your YouTube playlist</div><h1>'
            + title
            + '</h1><p class="lead">'
            + description
            + '</p><span class="badge">'
            + esc(status)
            + '</span><div class="actions">'
            + actions
            + "</div>"
            + draft_details(draft)
            + "</section>",
        )
    )


def error_page(message: str, status_code: int) -> HTMLResponse:
    title = {
        401: "Sign-in needed",
        403: "Request not approved",
        404: "Page unavailable",
        409: "This action is unavailable",
        429: "Time for a short pause",
    }.get(status_code, "Something needs attention")
    return HTMLResponse(
        shell(
            title,
            '<section class="center card"><div class="result-icon warning" aria-hidden="true">!</div><div class="eyebrow">Let’s get you back on track</div><h1>'
            + title
            + '</h1><p class="lead">'
            + esc(message)
            + '</p><p class="muted">For an expired connection, return to your AI client and start a fresh sign-in. For a playlist, reopen your own draft link and review it again.</p><div class="actions"><a class="button secondary" href="/">Back to home</a></div></section>',
        ),
        status_code=status_code,
        headers={"Vary": "Accept"},
    )
