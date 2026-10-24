"""Parses WhatsApp "Export chat" text files (Android and iOS styles)."""
import re

# 12/03/2026, 4:15 pm - Ravi: message      (Android)
# [12/03/26, 16:15:02] Ravi: message        (iOS)
LINE = re.compile(
    r"^\[?(\d{1,2}/\d{1,2}/\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?\s?(?:[ap]\.?m\.?)?)\]?\s*-?\s*([^:]{1,60}?):\s(.*)$",
    re.I,
)
SKIP = ("<media omitted>", "(file attached)", "this message was deleted", "messages and calls are end-to-end")


def clean(text: str) -> str:
    # newer exports use narrow no-break spaces and invisible marks
    return text.replace("\u202f", " ").replace("\u200e", "").replace("\ufeff", "")


def parse_chat(text: str) -> list[dict]:
    msgs: list[dict] = []
    for line in clean(text).splitlines():
        m = LINE.match(line)
        if m:
            date, time, sender, body = m.groups()
            msgs.append(
                {"id": len(msgs) + 1, "date": date, "time": time.strip(),
                 "sender": sender.strip(), "text": body.strip()}
            )
        elif msgs and line.strip():
            msgs[-1]["text"] += "\n" + line.strip()  # multi-line message
    return [m for m in msgs if not any(s in m["text"].lower() for s in SKIP)]
