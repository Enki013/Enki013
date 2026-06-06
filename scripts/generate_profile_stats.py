#!/usr/bin/env python3
import datetime as dt
import html
import json
import os
import pathlib
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo


ROOT = pathlib.Path(__file__).resolve().parents[1]
THEME = {
    "bg": "#0d1117",
    "border": "#30363d",
    "text": "#e6edf3",
    "muted": "#7d8590",
    "accent": "#f85149",
    "green": "#3fb950",
    "orange": "#d29922",
    "blue": "#58a6ff",
    "purple": "#bc8cff",
}


def local_today():
    timezone = os.environ.get("PROFILE_STATS_TIMEZONE", "Europe/Istanbul")
    try:
        return dt.datetime.now(ZoneInfo(timezone)).date()
    except Exception:
        return dt.datetime.now(dt.timezone.utc).date()


QUERY = """
query ProfileStats($login: String!, $from: DateTime!, $to: DateTime!, $after: String) {
  user(login: $login) {
    login
    name
    createdAt
    followers {
      totalCount
    }
    following {
      totalCount
    }
    repositories(
      ownerAffiliations: OWNER
      privacy: PUBLIC
      first: 100
      after: $after
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      totalCount
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        name
        isFork
        isArchived
        stargazerCount
        forkCount
        primaryLanguage {
          name
          color
        }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node {
              name
              color
            }
          }
        }
      }
    }
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalRepositoryContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def api_request(token, payload):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Enki013-profile-stats",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub API request failed: {exc.code} {detail}") from exc

    if result.get("errors"):
        raise SystemExit(f"GitHub API returned errors: {result['errors']}")
    return result["data"]["user"]


def collect_stats():
    token = os.environ.get("GITHUB_TOKEN")
    login = os.environ.get("GITHUB_USERNAME") or os.environ.get("GITHUB_REPOSITORY_OWNER")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required.")
    if not login:
        raise SystemExit("GITHUB_USERNAME or GITHUB_REPOSITORY_OWNER is required.")

    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=365)
    variables = {
        "login": login,
        "from": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "after": None,
    }

    repos = []
    user = None
    while True:
        user = api_request(token, {"query": QUERY, "variables": variables})
        if not user:
            raise SystemExit(f"GitHub user not found: {login}")
        repos.extend(user["repositories"]["nodes"])
        page_info = user["repositories"]["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        variables["after"] = page_info["endCursor"]

    user["repositories"]["nodes"] = repos
    return user


def esc(value):
    return html.escape(str(value), quote=True)


def compact(number):
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}k"
    return str(number)


def contribution_days(user):
    days = []
    calendar = user["contributionsCollection"]["contributionCalendar"]
    for week in calendar["weeks"]:
        for day in week["contributionDays"]:
            days.append((dt.date.fromisoformat(day["date"]), day["contributionCount"]))
    return sorted(days)


def streaks(days):
    longest = 0
    running = 0
    for _, count in days:
        running = running + 1 if count > 0 else 0
        longest = max(longest, running)

    current = 0
    reversed_days = list(reversed(days))
    if reversed_days and reversed_days[0][0] >= local_today() and reversed_days[0][1] == 0:
        reversed_days = reversed_days[1:]
    for _, count in reversed_days:
        if count <= 0:
            break
        current += 1
    return current, longest


def language_totals(repos):
    totals = {}
    colors = {}
    for repo in repos:
        if repo["isFork"]:
            continue
        for edge in repo["languages"]["edges"]:
            language = edge["node"]["name"]
            totals[language] = totals.get(language, 0) + edge["size"]
            colors[language] = edge["node"].get("color") or THEME["blue"]
    return totals, colors


def card_shell(width, height, title, body):
    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">{esc(title)}</title>
  <desc id="desc">Generated by GitHub Actions from GitHub API data.</desc>
  <style>
    .title {{ fill: {THEME["text"]}; font: 600 18px 'Segoe UI', Arial, sans-serif; }}
    .label {{ fill: {THEME["muted"]}; font: 500 13px 'Segoe UI', Arial, sans-serif; }}
    .value {{ fill: {THEME["text"]}; font: 700 26px 'Segoe UI', Arial, sans-serif; }}
    .small {{ fill: {THEME["muted"]}; font: 500 12px 'Segoe UI', Arial, sans-serif; }}
  </style>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="8" fill="{THEME["bg"]}" stroke="{THEME["border"]}"/>
  <text class="title" x="24" y="34">{esc(title)}</text>
{body}
</svg>
"""


def render_stats_card(user, repos):
    contrib = user["contributionsCollection"]
    non_fork_repos = [repo for repo in repos if not repo["isFork"]]
    stars = sum(repo["stargazerCount"] for repo in non_fork_repos)
    forks = sum(repo["forkCount"] for repo in non_fork_repos)
    total_contrib = contrib["contributionCalendar"]["totalContributions"]
    values = [
        ("Total Stars", compact(stars), THEME["orange"]),
        ("Total Forks", compact(forks), THEME["blue"]),
        ("Public Repos", compact(len(non_fork_repos)), THEME["purple"]),
        ("Contributions", compact(total_contrib), THEME["green"]),
    ]
    cells = []
    for index, (label, value, color) in enumerate(values):
        x = 24 + (index % 2) * 184
        y = 66 + (index // 2) * 62
        cells.append(f'  <circle cx="{x + 8}" cy="{y - 5}" r="5" fill="{color}"/>')
        cells.append(f'  <text class="label" x="{x + 22}" y="{y}">{esc(label)}</text>')
        cells.append(f'  <text class="value" x="{x}" y="{y + 32}">{esc(value)}</text>')

    cells.append(f'  <text class="small" x="24" y="170">Last updated: {esc(local_today().isoformat())}</text>')
    return card_shell(420, 190, f"{user['login']} GitHub Stats", "\n".join(cells))


def render_language_card(user, repos):
    totals, colors = language_totals(repos)
    top = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:5]
    total = sum(totals.values()) or 1
    rows = []
    y = 64
    for language, size in top:
        percent = size / total
        width = max(4, int(330 * percent))
        rows.append(f'  <text class="label" x="24" y="{y}">{esc(language)}</text>')
        rows.append(f'  <text class="small" x="360" y="{y}" text-anchor="end">{percent * 100:.1f}%</text>')
        rows.append(f'  <rect x="24" y="{y + 12}" width="330" height="8" rx="4" fill="#21262d"/>')
        rows.append(f'  <rect x="24" y="{y + 12}" width="{width}" height="8" rx="4" fill="{esc(colors.get(language, THEME["blue"]))}"/>')
        y += 35

    if not top:
        rows.append('  <text class="label" x="24" y="92">No language data available yet.</text>')

    return card_shell(420, 230, "Most Used Languages", "\n".join(rows))


def render_streak_card(user):
    days = contribution_days(user)
    current, longest = streaks(days)
    total = user["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    body = f"""
  <text class="label" x="42" y="76">Current Streak</text>
  <text class="value" x="42" y="116">{current} days</text>
  <text class="label" x="300" y="76">Longest Streak</text>
  <text class="value" x="300" y="116">{longest} days</text>
  <text class="label" x="558" y="76">Last 365 Days</text>
  <text class="value" x="558" y="116">{compact(total)}</text>
  <line x1="42" y1="142" x2="738" y2="142" stroke="{THEME["border"]}"/>
  <text class="small" x="42" y="168">Generated daily with GitHub Actions. No third-party stats service is used at README render time.</text>
"""
    return card_shell(780, 190, f"{user['login']} Contribution Streak", body)


def write_file(path, content):
    full_path = ROOT / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")
    print(f"Wrote {path}")


def main():
    user = collect_stats()
    repos = user["repositories"]["nodes"]
    write_file("profile/streak-dark.svg", render_streak_card(user))
    write_file("profile-summary-card-output/github_dark/3-stats.svg", render_stats_card(user, repos))
    write_file("profile-summary-card-output/github_dark/1-repos-per-language.svg", render_language_card(user, repos))


if __name__ == "__main__":
    main()
