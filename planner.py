"""
=============================================================
  planner.py  —  turning a big goal into a real plan
=============================================================

Give it "become a web developer in 1 month" and it produces a
week-by-week curriculum, then a PROPOSED schedule of study
sessions.

IMPORTANT: proposed. Nothing lands on your timeline until you
approve it, and you can change the time first. The assistant
suggests; you decide.

WHY NO AI HERE (yet)

Phase 17 adds a real AI assistant, which needs an API key and
costs money per request. This module does the same job with
plain Python: a library of curriculum templates plus a
keyword matcher.

The trade-off is honest:
  - templates: instant, free, offline, predictable — but only
    knows the subjects it has been taught
  - AI: handles any goal you can imagine — but needs a key,
    a network, and money

The seam is deliberate. app.py calls build_curriculum(); it
does not care whether the answer came from a template or a
language model. Swapping in AI later means changing this one
function, nothing else.
"""

import re
from datetime import datetime, timedelta

# -------------------------------------------------------------
# CURRICULUM TEMPLATES
# -------------------------------------------------------------
# Each is a list of weekly topic lists. If a goal needs more
# weeks than the template has, later weeks become practice and
# project time — which is genuinely how learning works.

TEMPLATES = {
    "web development": [
        ["HTML basics", "Semantic HTML", "CSS fundamentals",
         "Flexbox", "CSS Grid", "Build a static page"],
        ["JavaScript variables", "Functions", "Conditions and loops",
         "Arrays and objects", "The DOM", "Build an interactive page"],
        ["Git and GitHub", "Working with APIs", "Fetch and async",
         "Responsive design", "Debugging", "Small project"],
        ["Plan the final project", "Build the final project",
         "Testing", "Fixing problems", "Deployment", "Review and polish"],
    ],
    "python": [
        ["Variables and types", "Strings and numbers", "Lists and dicts",
         "Conditions", "Loops", "Small exercises"],
        ["Functions", "Modules and imports", "Files and folders",
         "Errors and exceptions", "Standard library tour", "Practice"],
        ["Classes and objects", "Working with data", "Virtual environments",
         "Installing packages", "Testing basics", "Small project"],
        ["Plan the final project", "Build the final project",
         "Refactoring", "Testing", "Documentation", "Review"],
    ],
    "data analysis": [
        ["What data analysis is", "Spreadsheets to code", "Python basics",
         "Loading a dataset", "Cleaning data", "First summary"],
        ["Pandas fundamentals", "Filtering and grouping", "Joining data",
         "Missing values", "Descriptive statistics", "Practice"],
        ["Charts that communicate", "Matplotlib", "Choosing the right chart",
         "Telling a story with data", "Dashboards", "Small project"],
        ["Plan the final analysis", "Do the analysis",
         "Write up findings", "Present clearly", "Review", "Next steps"],
    ],
    "fitness": [
        ["Baseline assessment", "Movement basics", "Warm-up routine",
         "Light cardio", "Mobility work", "Rest and recovery"],
        ["Strength fundamentals", "Upper body", "Lower body",
         "Core work", "Cardio progression", "Active recovery"],
        ["Increase intensity", "Circuit training", "Endurance session",
         "Technique review", "Nutrition basics", "Rest day"],
        ["Peak week planning", "Full workout", "Progress test",
         "Adjust the plan", "Recovery", "Set the next goal"],
    ],
    "language": [
        ["Alphabet and sounds", "Greetings", "Numbers 1-100",
         "Introducing yourself", "Common verbs", "First conversation"],
        ["Present tense", "Everyday vocabulary", "Asking questions",
         "Food and shopping", "Listening practice", "Short dialogue"],
        ["Past tense", "Describing things", "Directions and travel",
         "Reading practice", "Writing practice", "Conversation practice"],
        ["Future tense", "Longer conversations", "Watch something native",
         "Write a short piece", "Review weak areas", "Speaking test"],
    ],
    "writing": [
        ["Why you write", "Finding ideas", "Sentence craft",
         "Paragraphs", "Reading like a writer", "First draft"],
        ["Structure", "Openings", "Endings", "Voice and tone",
         "Editing basics", "Second piece"],
        ["Rewriting", "Cutting words", "Feedback", "Common mistakes",
         "Style", "Third piece"],
        ["Plan a longer piece", "Draft it", "Revise it",
         "Polish it", "Publish or share", "Plan what's next"],
    ],
    "study": [
        ["Map the syllabus", "Gather materials", "Chapter 1",
         "Chapter 2", "Review notes", "Self-test"],
        ["Chapter 3", "Chapter 4", "Chapter 5",
         "Summary notes", "Practice questions", "Self-test"],
        ["Weak areas", "Past papers", "Timed practice",
         "Review mistakes", "Group topics", "Self-test"],
        ["Full revision", "Mock exam", "Review mock",
         "Final weak areas", "Light review", "Rest before the exam"],
    ],
}

# Words that point at a template.
KEYWORDS = {
    "web development": ["web", "website", "frontend", "front-end", "html",
                        "css", "javascript", "react", "web developer",
                        "full stack", "fullstack"],
    "python": ["python", "programming", "coding", "code", "software",
               "developer", "backend", "back-end"],
    "data analysis": ["data", "analytics", "analyst", "pandas", "sql",
                      "statistics", "data science", "machine learning"],
    "fitness": ["fitness", "gym", "workout", "exercise", "run", "running",
                "marathon", "weight", "strength", "healthy", "training"],
    "language": ["language", "spanish", "french", "german", "chinese",
                 "japanese", "arabic", "italian", "portuguese", "korean",
                 "yoruba", "igbo", "hausa", "swahili", "speak"],
    "writing": ["writing", "write", "author", "blog", "novel", "book",
                "copywriting", "content"],
    "study": ["study", "exam", "course", "school", "university", "degree",
              "certification", "revision", "test", "class"],
}


def detect_subject(goal_text):
    """Which template best fits this goal? Returns a key or None."""
    text = goal_text.lower()
    best, best_score = None, 0
    for subject, words in KEYWORDS.items():
        score = sum(1 for w in words if w in text)
        if score > best_score:
            best, best_score = subject, score
    return best


def parse_duration(goal_text, default_weeks=4):
    """
    Pull a timeframe out of the goal text.

    "in one month" -> 4 weeks, "in 6 weeks" -> 6, "in 3 months" -> 12.
    """
    text = goal_text.lower()
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "a": 1, "an": 1}

    def number_before(unit):
        m = re.search(r"(\d+)\s*" + unit, text)
        if m:
            return int(m.group(1))
        for word, value in words.items():
            if re.search(rf"\b{word}\s+{unit}", text):
                return value
        return None

    months = number_before("month")
    if months:
        return max(1, min(months * 4, 52))
    weeks = number_before("week")
    if weeks:
        return max(1, min(weeks, 52))
    days = number_before("day")
    if days:
        return max(1, min(round(days / 7) or 1, 52))
    years = number_before("year")
    if years:
        return max(1, min(years * 52, 52))
    return default_weeks


def clean_goal_title(goal_text):
    """'I want to become a web developer in 1 month' -> 'Become a web developer'."""
    text = goal_text.strip()
    text = re.sub(r"^(i\s+want\s+to|i'd\s+like\s+to|i\s+would\s+like\s+to|"
                  r"help\s+me\s+to|help\s+me|i\s+need\s+to|my\s+goal\s+is\s+to)\s+",
                  "", text, flags=re.I)
    text = re.sub(r"\s+in\s+(\d+|one|two|three|four|five|six|seven|eight|"
                  r"nine|ten|a|an)\s+(day|week|month|year)s?\.?$", "",
                  text, flags=re.I)
    text = text.strip(" .")
    return (text[0].upper() + text[1:]) if text else "My goal"


def build_curriculum(goal_text, weeks):
    """
    Turn a goal into a week-by-week plan.

    Returns [{"week": 1, "topics": [...]}, ...]
    """
    subject = detect_subject(goal_text)
    template = TEMPLATES.get(subject)

    if not template:
        # No template matched. Rather than invent fake expertise,
        # give an honest generic structure the user can edit.
        template = [
            ["Learn the basics", "Gather resources", "First practice",
             "Second practice", "Review", "Small exercise"],
            ["Go deeper", "Practice", "Practice", "Apply it",
             "Review", "Exercise"],
            ["Harder material", "Practice", "Real application",
             "Review mistakes", "Consolidate", "Small project"],
            ["Plan a final piece", "Build it", "Improve it",
             "Review", "Finish", "Plan what's next"],
        ]

    plan = []
    for w in range(weeks):
        if w < len(template):
            topics = list(template[w])
        else:
            # Beyond the template: practice and projects.
            n = w - len(template) + 1
            topics = [f"Project work {n}", "Practice", "Review weak areas",
                      "Apply what you know", "Consolidate", "Reflect"]
        plan.append({"week": w + 1, "topics": topics})
    return plan


# -------------------------------------------------------------
# PROPOSING A SCHEDULE
# -------------------------------------------------------------
def propose_schedule(plan, start_date, hour, minute, days_of_week,
                     sessions_per_week=None):
    """
    Lay the curriculum onto real dates.

    This is a PROPOSAL. Nothing is saved until the user accepts.
    The time comes from the user — we never invent one.

    Returns [{"date","hour","minute","topic","week"}, ...]
    """
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    days_of_week = sorted(set(days_of_week))
    if not days_of_week:
        return []

    per_week = sessions_per_week or len(days_of_week)
    sessions = []

    # Walk forward day by day, placing topics on matching weekdays.
    current = start
    for entry in plan:
        placed, guard = 0, 0
        topics = entry["topics"]
        # Spread the week's topics across the chosen days.
        chosen = topics[:per_week] if per_week < len(topics) else topics

        while placed < len(chosen) and guard < 400:
            guard += 1
            if current.weekday() in days_of_week:
                sessions.append({
                    "date": current.isoformat(),
                    "hour": hour,
                    "minute": minute,
                    "topic": (chosen[placed].get("title", "Session")
                              if isinstance(chosen[placed], dict)
                              else chosen[placed]),
                    "week": entry["week"],
                })
                placed += 1
            current += timedelta(days=1)

    return sessions
