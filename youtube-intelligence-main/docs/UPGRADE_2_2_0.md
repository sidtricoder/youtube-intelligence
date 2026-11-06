# Upgrade to 2.2.0

Deploy the complete project, preserving existing private configuration and encryption keys. No new Render variables, Google Cloud settings or database migration are required for this UI update. Restart/redeploy, then begin a fresh connector authorization to see the new consent dialog. Existing authorized connectors need not reconnect merely for styling.

The consent dialog opens in the browser tab used by the AI client's OAuth flow. The server cannot insert its own UI inside Claude/ChatGPT, replace Google's consent screen or force the client to launch a popup. A native HTML dialog provides focus containment, keyboard navigation, Allow and Cancel; Escape cancels. Without JavaScript the consent form remains visible and usable.

Cancel consumes the pending transaction and returns OAuth access_denied and the original state to the registered callback. It issues no authorization code and does not disconnect existing authorizations. Allow still requires the user's browser session, account match and CSRF token.

The home, playlist approval, result and browser error pages now share responsive ivory/teal styling. Exact draft contents remain available for inspection. Completed or uncertain writes do not present another creation form. Browser approvals show a human-readable result; API callers retain JSON responses and existing status codes.

Styles and scripts are self-contained, with no external font, tracking or asset service. The minimal dialog script uses a fresh CSP nonce; form destinations remain restricted to validated OAuth origins. Metadata and user-supplied client names remain HTML-escaped.

Initial Google read/write permission requests and optional, uncapped positive duration constraints from 2.1.0 are retained. Individual playlist writes still require explicit approval of the exact draft and its typed confirmation phrase.
