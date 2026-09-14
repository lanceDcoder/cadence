"""Server-side Gemini support for personalised long-term goal plans.

The browser never sees the API key.  This module returns validated plain
Python data so the rest of Cadence keeps the same review-before-save flow.
"""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import planner


GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.5-flash"


class AssistantError(Exception):
    """A safe, user-facing failure from the AI provider."""


def is_configured():
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


def _clean_plan(payload, goal, weeks):
    """Keep model output inside Cadence's existing, safe plan shape."""
    if not isinstance(payload, dict):
        raise AssistantError("The assistant returned an unusable plan. Please try again.")

    title = str(payload.get("title") or planner.clean_goal_title(goal)).strip()[:200]
    entries = payload.get("plan")
    if not isinstance(entries, list):
        raise AssistantError("The assistant returned an unusable plan. Please try again.")

    plan = []
    for week_number, entry in enumerate(entries[:weeks], start=1):
        topics = entry.get("topics") if isinstance(entry, dict) else None
        if not isinstance(topics, list):
            continue
        clean_topics = []
        for topic in topics[:7]:
            if isinstance(topic, dict):
                title = str(topic.get("title") or "").strip()[:200]
                details = str(topic.get("details") or "").strip()[:1200]
            else:
                title, details = str(topic).strip()[:200], ""
            if title:
                clean_topics.append({"title": title, "details": details})
        if clean_topics:
            plan.append({"week": week_number, "topics": clean_topics})

    if not plan:
        raise AssistantError("The assistant did not return any usable sessions. Please try again.")

    # A complete schedule is more useful than a partial one. The existing,
    # predictable planner fills only any missing weeks.
    fallback = planner.build_curriculum(goal, weeks)
    while len(plan) < weeks:
        week_number = len(plan) + 1
        plan.append({"week": week_number, "topics": [
            {"title": topic, "details": ""}
            for topic in fallback[week_number - 1]["topics"]
        ]})
    return {"title": title or "My goal", "weeks": weeks, "plan": plan}


def build_goal_plan(goal, weeks):
    """Ask Gemini for a concise, practical plan; never expose its key."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise AssistantError("AI planning is not configured yet.")

    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    instruction = (
        "You are Cadence, a supportive goal-planning assistant. Create a "
        "realistic, concise learning or action plan. Do not give medical, "
        "legal, financial, or dangerous instructions. The user must approve "
        "every proposed session before it is saved. Return JSON only, with "
        "this exact shape: {\"title\": string, \"plan\": "
        "[{\"week\": number, \"topics\": [{\"title\": string, "
        "\"details\": string}]}]}. Include exactly "
        f"{weeks} weeks, each with 3 to 7 specific, achievable topics. "
        "Each title must name one specific task; never use vague labels such as "
        "'Learn the basics', 'Practice', or 'Go deeper'. Each details value must "
        "be a 2-4 sentence, beginner-friendly explanation: define the exact skill, "
        "name the materials or techniques needed, give ordered actions, and end "
        "with a concrete completion or fit check. For craft goals, include gauge, "
        "measurements, construction order, and finishing steps where relevant. "
        "Make it practical and specific to the user's goal."
    )
    body = {
        "systemInstruction": {"parts": [{"text": instruction}]},
        "contents": [{"role": "user", "parts": [{
            "text": f"My goal: {goal[:2000]}\nTime available: {weeks} weeks."
        }]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.4,
            "maxOutputTokens": 4096,
        },
    }
    request = Request(
        GEMINI_API_URL.format(model=model),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise AssistantError("Gemini rejected the API key. Check GEMINI_API_KEY.") from exc
        if exc.code == 429:
            raise AssistantError("Gemini is busy or its request limit was reached. Try again shortly.") from exc
        raise AssistantError("The AI planner is temporarily unavailable. Try again shortly.") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise AssistantError("The AI planner is temporarily unavailable. Try again shortly.") from exc

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return _clean_plan(json.loads(text), goal, weeks)
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AssistantError("The assistant returned an unusable plan. Please try again.") from exc
