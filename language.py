"""
=============================================================
  language.py  —  understanding what you typed or said
=============================================================

Turns "I need to call Sarah at 7 PM" into:
    title = "Call Sarah",  hour = 19,  minute = 0

WHY THIS IS NOT AI

Real AI (Phase 17) needs an API key, a network connection and
money per request. For extracting a task and a time, plain
pattern matching is genuinely better: instant, free, offline,
and completely predictable.

THE MOST IMPORTANT RULE IN THIS FILE

If we cannot find a clear time, we return time=None and the app
REFUSES to schedule it. It asks you instead.

Your principle: the app never invents a time. A parser that
guesses "probably morning" would break that on day one. So
this one is deliberately strict — it would rather admit it
doesn't know.

AMBIGUITY IS FLAGGED, NOT GUESSED

"call John at 6" is genuinely ambiguous: 6 AM or 6 PM? We do
apply one conservative convention — a bare 1-7 means PM,
because "meet me at 6" almost never means dawn — but we mark
the result `ambiguous` so the interface can confirm rather
than silently commit.
"""

import re

# Words people use before the actual task.
LEAD_INS = [
    r"^i\s+need\s+to\s+", r"^i\s+have\s+to\s+", r"^i\s+want\s+to\s+",
    r"^i\s+should\s+", r"^i\s+must\s+", r"^i'?ll\s+", r"^i\s+am\s+going\s+to\s+",
    r"^remind\s+me\s+to\s+", r"^remind\s+me\s+", r"^please\s+remind\s+me\s+to\s+",
    r"^don'?t\s+let\s+me\s+forget\s+to\s+", r"^make\s+sure\s+i\s+",
    r"^i\s+gotta\s+", r"^gotta\s+", r"^need\s+to\s+", r"^have\s+to\s+",
    r"^schedule\s+", r"^add\s+", r"^set\s+a\s+reminder\s+to\s+",
    r"^today\s+i\s+need\s+to\s+", r"^today\s+", r"^also\s+",
    r"^then\s+", r"^and\s+then\s+", r"^and\s+", r"^plus\s+",
]

TRAILING_JUNK = [
    r"\s+please$", r"\s+thanks$", r"\s+thank\s+you$", r"\s+ok$", r"\s+okay$",
]


def _strip_lead_ins(text):
    changed = True
    while changed:
        changed = False
        for pattern in LEAD_INS:
            new = re.sub(pattern, "", text, flags=re.I)
            if new != text:
                text, changed = new, True
    return text.strip()


def extract_time(text):
    """
    Find a time in the text.

    Returns (hour, minute, matched_text, ambiguous) or None.
    """
    t = text.lower()

    # --- named times, unambiguous ---
    named = {
        r"\bat\s+noon\b": (12, 0), r"\bnoon\b": (12, 0),
        r"\bat\s+midnight\b": (0, 0), r"\bmidnight\b": (0, 0),
        r"\bmidday\b": (12, 0),
    }
    for pattern, (h, m) in named.items():
        match = re.search(pattern, t)
        if match:
            return h, m, match.group(0), False

    # --- 7:30 pm / 7.30pm / 7:30 ---
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm|a\.m\.|p\.m\.)?\b", t)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        suffix = (m.group(3) or "").replace(".", "")
        if minute > 59:
            return None
        if suffix.startswith("p") and hour < 12:
            hour += 12
        elif suffix.startswith("a") and hour == 12:
            hour = 0
        if hour > 23:
            return None
        # 24-hour clock like 19:30 is unambiguous; 7:30 with no
        # suffix is not.
        ambiguous = (not suffix) and hour <= 7
        if ambiguous:
            hour += 12          # conservative: "at 7:30" means evening
        return hour, minute, m.group(0), ambiguous

    # --- 7 pm / 7pm ---
    m = re.search(r"\b(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)\b", t)
    if m:
        hour = int(m.group(1))
        suffix = m.group(2).replace(".", "")
        if hour > 12:
            return None
        if suffix.startswith("p") and hour < 12:
            hour += 12
        elif suffix.startswith("a") and hour == 12:
            hour = 0
        return hour, 0, m.group(0), False

    # --- "at 6" with nothing else ---
    m = re.search(r"\bat\s+(\d{1,2})\b(?!\s*(?:st|nd|rd|th|%|kg|km|mins?|"
                  r"minutes?|hours?))", t)
    if m:
        hour = int(m.group(1))
        if hour > 23:
            return None
        # 1-7 almost certainly means afternoon/evening.
        ambiguous = 1 <= hour <= 7
        if ambiguous:
            hour += 12
        return hour, 0, m.group(0), ambiguous

    return None


def extract_date_hint(text):
    """
    Spot 'today' or 'tomorrow'. Returns 0, 1, or None.

    Deliberately narrow: "next Tuesday" is genuinely ambiguous
    and we'd rather ask than guess.
    """
    t = text.lower()
    if re.search(r"\btomorrow\b", t):
        return 1
    if re.search(r"\btoday\b|\btonight\b|\bthis\s+(morning|afternoon|evening)\b", t):
        return 0
    return None


def clean_title(text, time_match):
    """Remove the time phrase and tidy what's left into a task name."""
    title = text
    if time_match:
        # The matched text came from a lowercased copy, so match
        # case-insensitively here or "2 PM" survives in the title.
        title = re.sub(re.escape(time_match), " ", title, flags=re.I)
        # Remove a preposition left dangling by the removal:
        # "assignment at  " -> "assignment"
        title = re.sub(r"\s+(at|by|around|about|on)\s*$", " ",
                       title, flags=re.I)
        title = re.sub(r"\s+at\s+(?=$|\s)", " ", title, flags=re.I)

    # Remove day words FIRST. "Tomorrow I need to go..." only starts
    # with "I need to" once "Tomorrow" is gone, so stripping lead-ins
    # before this would miss it.
    title = re.sub(r"\b(today|tomorrow|tonight|this\s+morning|"
                   r"this\s+afternoon|this\s+evening)\b", " ", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip()
    title = _strip_lead_ins(title)

    for junk in TRAILING_JUNK:
        title = re.sub(junk, "", title, flags=re.I)

    title = re.sub(r"\s+", " ", title).strip(" ,.;:-")
    return (title[0].upper() + title[1:]) if title else ""


def split_multiple(text):
    """
    Break "do X at 2, do Y at 4 and call Z at 7" into pieces.

    Only splits where a time follows, so "buy rice, beans and oil
    at 5pm" stays as one task.
    """
    parts = re.split(r"(?:,|\band then\b|\bthen\b|\band also\b|\balso\b|"
                     r"\band\b|;)", text, flags=re.I)
    parts = [p.strip() for p in parts if p.strip()]

    merged, buffer = [], ""
    for part in parts:
        candidate = (buffer + " " + part).strip() if buffer else part
        if extract_time(part):
            merged.append(candidate)
            buffer = ""
        else:
            buffer = candidate
    if buffer:
        merged.append(buffer)
    return merged or [text]


def parse(text):
    """
    Parse ONE phrase into a task.

    Returns:
      {"title", "hour", "minute", "day_offset", "ambiguous", "ok", "reason"}

    ok=False means we could not find a time. The app must then
    ask rather than invent one.
    """
    original = (text or "").strip()
    if not original:
        return {"ok": False, "reason": "empty", "title": "",
                "hour": None, "minute": None, "day_offset": None,
                "ambiguous": False}

    found = extract_time(original)
    day_offset = extract_date_hint(original)

    if not found:
        return {"ok": False, "reason": "no_time",
                "title": clean_title(original, None),
                "hour": None, "minute": None,
                "day_offset": day_offset, "ambiguous": False}

    hour, minute, matched, ambiguous = found
    title = clean_title(original, matched)

    if not title:
        return {"ok": False, "reason": "no_title", "title": "",
                "hour": hour, "minute": minute,
                "day_offset": day_offset, "ambiguous": ambiguous}

    return {"ok": True, "reason": None, "title": title,
            "hour": hour, "minute": minute,
            "day_offset": day_offset, "ambiguous": ambiguous}


def parse_many(text):
    """Parse a sentence that may contain several tasks."""
    return [parse(part) for part in split_multiple(text or "")]
