"""
Utilities for parsing and rendering mentions in comments.

Mention syntax supported:
- @username  (organization member username)
- @team:Team Name  (team mention by human-readable name)

Rendering: wrap mentions in spans/links for display.
"""
import re
from typing import Dict
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.urls import reverse

USER_PATTERN = re.compile(r"(?P<prefix>^|\s)@(?P<username>[A-Za-z0-9_\.\-]+)")
TEAM_PATTERN = re.compile(r"(?P<prefix>^|\s)@team:(?P<teamname>[^@\n\r\t]+?)\b")


def parse_mentions(text: str):
    """Parse mentions in text.

    Returns dict with keys:
    - usernames: set of usernames mentioned
    - team_names: set of team names mentioned
    """
    if not text:
        return {"usernames": set(), "team_names": set()}
    usernames = {m.group('username').lower() for m in USER_PATTERN.finditer(text)}
    team_names = {m.group('teamname').strip() for m in TEAM_PATTERN.finditer(text)}
    return {"usernames": usernames, "team_names": team_names}


def render_mentions(text: str, users_by_username: Dict[str, object], teams_by_name: Dict[str, object]):
    """Render text with mentions converted to links/spans.

    users_by_username: mapping username -> UserProfile
    teams_by_name: mapping team name -> Team
    """
    if not text:
        return ""

    def replace_user(m):
        prefix = m.group('prefix')
        username = m.group('username')
        prof = users_by_username.get(username.lower())
        label = f"@{escape(username)}"
        if prof:
            # Link to a generic user page if exists; fallback to span
            try:
                url = reverse('admin:user_detail', args=[prof.id])  # may not exist; ignore
            except Exception:
                url = ''
            if url:
                return f"{prefix}<a class=\"text-purple-700 hover:text-purple-900 font-medium\" href=\"{url}\">{label}</a>"
        return f"{prefix}<span class=\"bg-purple-100 text-purple-800 px-1 rounded\">{label}</span>"

    def replace_team(m):
        prefix = m.group('prefix')
        teamname = m.group('teamname').strip()
        team = teams_by_name.get(teamname)
        label = f"@team:{escape(teamname)}"
        if team:
            try:
                url = reverse('cflows:team_detail', args=[team.id])
            except Exception:
                url = ''
            if url:
                return f"{prefix}<a class=\"text-blue-700 hover:text-blue-900 font-medium\" href=\"{url}\">{label}</a>"
        return f"{prefix}<span class=\"bg-blue-100 text-blue-800 px-1 rounded\">{label}</span>"

    # Escape first, then re-inject styled mentions
    safe_text = escape(text)
    # Recompute patterns on escaped content: still matches as '@'
    safe_text = USER_PATTERN.sub(replace_user, safe_text)
    safe_text = TEAM_PATTERN.sub(replace_team, safe_text)
    # Convert newlines
    safe_text = safe_text.replace('\n', '<br/>')
    return mark_safe(safe_text)
