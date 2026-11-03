"""Choose browser HTML only when it is explicitly acceptable and preferred."""


def prefers_html(accept: str) -> bool:
    entries: dict[str, float] = {}
    for part in accept.lower().split(","):
        media, *parameters = part.strip().split(";")
        quality = 1.0
        for parameter in parameters:
            key, _, value = parameter.strip().partition("=")
            if key == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        entries[media] = quality if 0 <= quality <= 1 else 0.0
    html = entries.get("text/html", 0.0)
    json = entries.get("application/json", entries.get("application/*", entries.get("*/*", 0.0)))
    return html > 0 and html >= json
