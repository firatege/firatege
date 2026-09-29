"""Generate self-hosted GitHub profile cards (stats, languages, activity) as SVG.

Runs in GitHub Actions; needs GITHUB_TOKEN (or a PAT in STATS_TOKEN to include
private contributions). Writes light and dark variants into ./assets.
"""

import json
import os
import sys
import urllib.request
from datetime import date
from html import escape
from pathlib import Path

USERNAME = os.environ.get("GH_USERNAME", "firatege")
OUT_DIR = Path(__file__).resolve().parent.parent / "assets"
API_URL = "https://api.github.com/graphql"

# Notebook byte counts include embedded outputs and swamp everything else.
EXCLUDED_LANGUAGES = {"Jupyter Notebook", "HTML", "CSS"}
TOP_LANGUAGES = 6

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace"

THEMES = {
    "dark": {
        "bg": "#0d1117", "border": "#21262d", "text": "#e6edf3",
        "muted": "#7d8590", "faint": "#161b22",
        "scale": ["#161b22", "#3d444d", "#6e7681", "#b1bac4", "#f0f6fc"],
    },
    "light": {
        "bg": "#ffffff", "border": "#d0d7de", "text": "#1f2328",
        "muted": "#656d76", "faint": "#f6f8fa",
        "scale": ["#ebeef1", "#c4c9cf", "#8c959f", "#57606a", "#1f2328"],
    },
}

QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    repositoriesContributedTo(contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]) { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount weekday } }
      }
    }
  }
}
"""


def fetch_user(token: str) -> dict:
    body = json.dumps({"query": QUERY, "variables": {"login": USERNAME}}).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={"Authorization": f"bearer {token}", "User-Agent": USERNAME},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    return payload["data"]["user"]


def summarize_languages(repos: list[dict]) -> list[tuple[str, float]]:
    totals: dict[str, int] = {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name not in EXCLUDED_LANGUAGES:
                totals[name] = totals.get(name, 0) + edge["size"]
    grand = sum(totals.values()) or 1
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    top = [(name, size / grand * 100) for name, size in ranked[:TOP_LANGUAGES]]
    rest = 100 - sum(pct for _, pct in top)
    return top + ([("Other", rest)] if rest >= 0.5 else [])


def compute_streaks(days: list[dict]) -> tuple[int, int]:
    longest = run = 0
    for day in days:
        run = run + 1 if day["contributionCount"] > 0 else 0
        longest = max(longest, run)
    current = 0
    # Today may still be empty; don't break the streak for it.
    tail = days[:-1] if days and days[-1]["contributionCount"] == 0 else days
    for day in reversed(tail):
        if day["contributionCount"] == 0:
            break
        current += 1
    return current, longest


def fmt(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 10_000 else f"{n:,}"


def svg_shell(width: int, height: int, theme: dict, title: str, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">'
        f"<title>{escape(title)}</title>"
        f"<style>text{{font-family:{FONT};fill:{theme['text']}}}"
        f".m{{fill:{theme['muted']}}}.n{{font-family:{MONO}}}"
        f".h{{font-size:11px;letter-spacing:.12em;fill:{theme['muted']}}}</style>"
        f'<rect x=".5" y=".5" width="{width - 1}" height="{height - 1}" rx="10" '
        f'fill="{theme["bg"]}" stroke="{theme["border"]}"/>{body}</svg>'
    )


def render_stats(user: dict, theme: dict) -> str:
    repos = user["repositories"]
    cal = user["contributionsCollection"]
    stars = sum(r["stargazerCount"] for r in repos["nodes"])
    total = cal["contributionCalendar"]["totalContributions"]
    rows = [
        ("Commits", cal["totalCommitContributions"] + cal["restrictedContributionsCount"]),
        ("Pull requests", user["pullRequests"]["totalCount"]),
        ("Issues", user["issues"]["totalCount"]),
        ("Public repos", repos["totalCount"]),
        ("Contributed to", user["repositoriesContributedTo"]["totalCount"]),
        ("Stars earned", stars),
    ]
    parts = [
        '<text x="28" y="40" class="h">OVERVIEW</text>',
        f'<text x="28" y="98" class="n" font-size="46" font-weight="600">{fmt(total)}</text>',
        '<text x="28" y="122" class="m" font-size="13">contributions in the last year</text>',
    ]
    col_x, row_y = (250, 332), 40
    for i, (label, value) in enumerate(rows):
        x = col_x[i % 2]
        y = row_y + (i // 2) * 52
        parts.append(f'<text x="{x}" y="{y + 12}" class="m" font-size="12">{label}</text>')
        parts.append(
            f'<text x="{x}" y="{y + 36}" class="n" font-size="20" font-weight="600">{fmt(value)}</text>'
        )
    parts.append(f'<line x1="226" y1="30" x2="226" y2="176" stroke="{theme["border"]}"/>')
    return svg_shell(415, 200, theme, "GitHub stats", "".join(parts))


def render_languages(langs: list[tuple[str, float]], theme: dict) -> str:
    shades = [theme["text"], theme["scale"][3], theme["scale"][2],
              theme["scale"][1], theme["muted"], theme["border"], theme["faint"]]
    bar_x, bar_w, parts, cursor = 28, 359, ['<text x="28" y="40" class="h">LANGUAGES</text>'], 28.0
    parts.append(f'<clipPath id="bar"><rect x="{bar_x}" y="58" width="{bar_w}" height="10" rx="5"/></clipPath><g clip-path="url(#bar)">')
    for i, (_, pct) in enumerate(langs):
        w = bar_w * pct / 100
        parts.append(f'<rect x="{cursor:.2f}" y="58" width="{w + 0.5:.2f}" height="10" fill="{shades[i]}"/>')
        cursor += w
    parts.append("</g>")
    for i, (name, pct) in enumerate(langs):
        x = 28 + (i % 2) * 186
        y = 100 + (i // 2) * 28
        parts.append(f'<circle cx="{x + 5}" cy="{y - 4}" r="5" fill="{shades[i]}" stroke="{theme["border"]}"/>')
        parts.append(f'<text x="{x + 18}" y="{y}" font-size="13">{escape(name)}</text>')
        parts.append(f'<text x="{x + 170}" y="{y}" class="m n" font-size="12" text-anchor="end">{pct:.1f}%</text>')
    return svg_shell(415, 200, theme, "Most used languages", "".join(parts))


def level(count: int, peak: int) -> int:
    if count == 0:
        return 0
    return min(4, 1 + int(3 * count / max(peak, 1)))


def render_activity(user: dict, theme: dict) -> str:
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    days = [d for w in weeks for d in w["contributionDays"]]
    current, longest = compute_streaks(days)
    peak = sorted(d["contributionCount"] for d in days)[int(len(days) * 0.95)] or 1
    cell, gap, left, top = 11.8, 3, 28, 78
    parts = [
        '<text x="28" y="40" class="h">ACTIVITY · LAST 12 MONTHS</text>',
        f'<text x="812" y="40" text-anchor="end" font-size="13"><tspan class="m">Current streak </tspan>'
        f'<tspan class="n" font-weight="600">{current}d</tspan><tspan class="m">   ·   Longest </tspan>'
        f'<tspan class="n" font-weight="600">{longest}d</tspan></text>',
    ]
    last_month = None
    for wi, week in enumerate(weeks):
        x = round(left + wi * (cell + gap), 1)
        first = date.fromisoformat(week["contributionDays"][0]["date"])
        if first.month != last_month and first.day <= 7 and wi < len(weeks) - 2:
            parts.append(f'<text x="{x}" y="{top - 10}" class="m" font-size="10">{first:%b}</text>')
            last_month = first.month
        for d in week["contributionDays"]:
            y = round(top + d["weekday"] * (cell + gap), 1)
            fill = theme["scale"][level(d["contributionCount"], peak)]
            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{fill}">'
                f'<title>{d["contributionCount"]} on {d["date"]}</title></rect>'
            )
    legend_y = round(top + 7 * (cell + gap) + 12)
    swatch_x = 812 - 30 - 5 * (cell + gap)
    parts.append(f'<text x="{swatch_x - 6:.1f}" y="{legend_y + 9}" class="m" font-size="10" text-anchor="end">Less</text>')
    for i, shade in enumerate(theme["scale"]):
        parts.append(f'<rect x="{swatch_x + i * (cell + gap):.1f}" y="{legend_y}" width="{cell}" height="{cell}" rx="2" fill="{shade}"/>')
    parts.append(f'<text x="812" y="{legend_y + 9}" class="m" font-size="10" text-anchor="end">More</text>')
    return svg_shell(840, legend_y + 34, theme, "Contribution activity", "".join(parts))


def main() -> int:
    token = os.environ.get("STATS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Set GITHUB_TOKEN or STATS_TOKEN", file=sys.stderr)
        return 1
    user = fetch_user(token)
    langs = summarize_languages(user["repositories"]["nodes"])
    OUT_DIR.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        (OUT_DIR / f"stats-{name}.svg").write_text(render_stats(user, theme))
        (OUT_DIR / f"languages-{name}.svg").write_text(render_languages(langs, theme))
        (OUT_DIR / f"activity-{name}.svg").write_text(render_activity(user, theme))
    print(f"Wrote cards to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
