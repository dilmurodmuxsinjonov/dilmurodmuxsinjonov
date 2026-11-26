"""Self-hosted GitHub GraphQL telemetry SVG generator (Python 3 stdlib only)."""

from __future__ import annotations

import html
import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GRAPHQL_URL = "https://api.github.com/graphql"
ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT_DIR / "assets"

GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalPullRequestReviewContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
    repositories(
      first: 100
      ownerAffiliations: OWNER
      isFork: false
      privacy: PUBLIC
      orderBy: { field: PUSHED_AT, direction: DESC }
    ) {
      totalCount
      nodes {
        name
        pushedAt
        stargazerCount
        isArchived
        languages(first: 10, orderBy: { field: SIZE, direction: DESC }) {
          edges {
            size
            node {
              name
            }
          }
        }
      }
    }
  }
}
"""

FONT_SERIF = "Georgia, 'Times New Roman', serif"
FONT_SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
FONT_MONO = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"


@dataclass(frozen=True)
class Theme:
    name: str
    bg_start: str
    bg_end: str
    border: str
    border_opacity: str
    hairline: str
    hairline_opacity: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent_gold: str
    bar_mid: str
    bar_low: str
    bar_zero: str
    lang_palette: tuple[str, ...]


THEMES: dict[str, Theme] = {
    "dark": Theme(
        name="dark",
        bg_start="#0B0B0D",
        bg_end="#070708",
        border="#FFFFFF",
        border_opacity="0.10",
        hairline="#FFFFFF",
        hairline_opacity="0.08",
        text_primary="#F1F1EE",
        text_secondary="#B9BDC2",
        text_muted="#9699A0",
        accent_gold="#C9A86A",
        bar_mid="#A3A8B0",
        bar_low="#4A4E56",
        bar_zero="#222429",
        lang_palette=("#C9A86A", "#E6E4DE", "#A3A8B0", "#6F747D", "#4A4E56", "#3E434C"),
    ),
    "light": Theme(
        name="light",
        bg_start="#FAF8F5",
        bg_end="#F2EEE6",
        border="#DED8CC",
        border_opacity="1",
        hairline="#E2DCD0",
        hairline_opacity="1",
        text_primary="#141413",
        text_secondary="#4E4D49",
        text_muted="#64615A",
        accent_gold="#9E7B3B",
        bar_mid="#5D5A54",
        bar_low="#B2AEA5",
        bar_zero="#E4DFD5",
        lang_palette=("#9E7B3B", "#262523", "#5D5A54", "#8A867E", "#B2AEA5", "#D6D1C7"),
    ),
}


@dataclass(frozen=True)
class TelemetryMetrics:
    total_contributions: int
    commits: int
    pull_requests: int
    issues: int
    reviews: int
    public_repos: int
    total_stars: int
    weekly_counts: tuple[int, ...]
    max_week: int
    last_activity_date: str
    languages: tuple[tuple[str, float], ...]


def fetch_github_telemetry(username: str, token: str) -> dict[str, Any]:
    """Fetch user contributions and repository metrics via GitHub GraphQL API."""
    payload = json.dumps({"query": GRAPHQL_QUERY, "variables": {"login": username}}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "User-Agent": f"profile-telemetry-generator/{username}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub GraphQL HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub GraphQL network error: {exc.reason}") from exc

    if body.get("errors"):
        raise RuntimeError(f"GitHub GraphQL returned errors: {json.dumps(body['errors'])}")

    user = (body.get("data") or {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user '{username}' was not found.")
    return user


def aggregate_metrics(user: dict[str, Any]) -> TelemetryMetrics:
    """Aggregate contribution ledger, 12-week cadence, and language mix."""
    contrib = user["contributionsCollection"]
    calendar = contrib["contributionCalendar"]
    weeks = calendar.get("weeks") or []

    recent_weeks = weeks[-12:]
    weekly_counts = [
        sum(int(day.get("contributionCount", 0)) for day in week.get("contributionDays") or [])
        for week in recent_weeks
    ]
    if len(weekly_counts) < 12:
        weekly_counts = [0] * (12 - len(weekly_counts)) + weekly_counts
    max_week = max(weekly_counts) if any(weekly_counts) else 0

    activity_dates: list[str] = []
    for week in weeks:
        for day in week.get("contributionDays") or []:
            if int(day.get("contributionCount", 0)) > 0 and day.get("date"):
                activity_dates.append(str(day["date"])[:10])

    repos_data = user["repositories"]
    repo_nodes = repos_data.get("nodes") or []
    total_stars = sum(int(repo.get("stargazerCount", 0)) for repo in repo_nodes)

    lang_totals: dict[str, int] = {}
    for repo in repo_nodes:
        pushed_at = repo.get("pushedAt")
        if pushed_at:
            activity_dates.append(str(pushed_at)[:10])
        if repo.get("isArchived"):
            continue
        edges = (repo.get("languages") or {}).get("edges") or []
        for edge in edges:
            size = int(edge.get("size", 0))
            name = (edge.get("node") or {}).get("name")
            if size > 0 and name:
                lang_totals[name] = lang_totals.get(name, 0) + size

    total_lang_bytes = sum(lang_totals.values())
    sorted_langs = sorted(lang_totals.items(), key=lambda item: item[1], reverse=True)

    languages: list[tuple[str, float]] = []
    if total_lang_bytes > 0:
        top_five = sorted_langs[:5]
        other_bytes = sum(size for _, size in sorted_langs[5:])
        for name, size in top_five:
            pct = round((size / total_lang_bytes) * 100.0, 1)
            if pct > 0:
                languages.append((name, pct))
        if other_bytes > 0:
            other_pct = round((other_bytes / total_lang_bytes) * 100.0, 1)
            if other_pct > 0:
                languages.append(("Other", other_pct))

    last_activity_date = max(activity_dates) if activity_dates else "N/A"

    return TelemetryMetrics(
        total_contributions=int(calendar.get("totalContributions", 0)),
        commits=int(contrib.get("totalCommitContributions", 0)),
        pull_requests=int(contrib.get("totalPullRequestContributions", 0)),
        issues=int(contrib.get("totalIssueContributions", 0)),
        reviews=int(contrib.get("totalPullRequestReviewContributions", 0)),
        public_repos=int(repos_data.get("totalCount", len(repo_nodes))),
        total_stars=total_stars,
        weekly_counts=tuple(weekly_counts),
        max_week=max_week,
        last_activity_date=last_activity_date,
        languages=tuple(languages),
    )


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _truncate_label(label: str, limit: int = 12) -> str:
    return label if len(label) <= limit else f"{label[: limit - 1]}…"


def _render_cadence_bars(metrics: TelemetryMetrics, theme: Theme) -> str:
    peak = metrics.max_week
    bars: list[str] = []
    start_x = 442
    baseline_y = 194
    max_height = 86

    for idx, count in enumerate(metrics.weekly_counts):
        x = start_x + idx * 27
        if count <= 0 or peak <= 0:
            height = 4
            fill = theme.bar_zero
        else:
            ratio = count / peak
            scaled = ratio ** 0.65
            height = max(8, round(scaled * max_height))
            if count == peak:
                fill = theme.accent_gold
            elif ratio >= 0.45:
                fill = theme.bar_mid
            else:
                fill = theme.bar_low
        y = baseline_y - height
        bars.append(f'  <rect x="{x}" y="{y}" width="18" height="{height}" rx="2" fill="{fill}"/>')
    return "\n".join(bars)


def _render_language_bar_and_legend(metrics: TelemetryMetrics, theme: Theme) -> str:
    if not metrics.languages:
        return (
            f'  <rect x="822" y="102" width="342" height="8" rx="4" fill="{theme.bar_zero}"/>\n'
            f'  <text x="822" y="142" font-family="{FONT_SANS}" font-size="12" '
            f'fill="{theme.text_muted}">No public language data available.</text>'
        )

    bar_x = 822
    bar_y = 102
    bar_width = 342
    bar_height = 8
    gap = 2
    n_langs = len(metrics.languages)
    usable_width = bar_width - gap * max(0, n_langs - 1)
    total_pct = sum(pct for _, pct in metrics.languages) or 1.0

    raw_widths = [max(4, round((pct / total_pct) * usable_width)) for _, pct in metrics.languages]
    delta = usable_width - sum(raw_widths)
    if raw_widths:
        max_idx = max(range(len(raw_widths)), key=lambda i: raw_widths[i])
        raw_widths[max_idx] = max(4, raw_widths[max_idx] + delta)

    parts: list[str] = []
    cursor_x = bar_x
    for idx, ((_, _), seg_w) in enumerate(zip(metrics.languages, raw_widths)):
        color = theme.lang_palette[idx % len(theme.lang_palette)]
        parts.append(
            f'    <rect x="{cursor_x}" y="{bar_y}" width="{seg_w}" height="{bar_height}" fill="{color}"/>'
        )
        cursor_x += seg_w + gap

    legend_rows = (138, 172, 206)
    legend_cols = ((822, 982), (1004, 1164))
    legend_parts: list[str] = []
    for idx, (name, pct) in enumerate(metrics.languages[:6]):
        row_idx = idx // 2
        col_idx = idx % 2
        lx, rx = legend_cols[col_idx]
        ly = legend_rows[row_idx]
        color = theme.lang_palette[idx % len(theme.lang_palette)]
        label = _esc(_truncate_label(name))
        pct_text = _esc(f"{pct:.1f}%")
        legend_parts.append(
            f'  <rect x="{lx}" y="{ly - 9}" width="8" height="8" rx="2" fill="{color}"/>\n'
            f'  <text x="{lx + 15}" y="{ly}" font-family="{FONT_SANS}" font-size="12" font-weight="500" '
            f'fill="{theme.text_secondary}">{label}</text>\n'
            f'  <text x="{rx}" y="{ly}" text-anchor="end" font-family="{FONT_MONO}" font-size="12" '
            f'font-weight="500" fill="{theme.text_primary}">{pct_text}</text>'
        )

    bar_block = '  <g clip-path="url(#langClip)">\n' + "\n".join(parts) + "\n  </g>"
    return bar_block + "\n" + "\n".join(legend_parts)


def render_telemetry_svg(metrics: TelemetryMetrics, theme: Theme) -> str:
    """Render a Quiet Authority 3-column telemetry SVG for the specified theme."""
    repo_label = "repository" if metrics.public_repos == 1 else "repositories"
    star_label = "star" if metrics.total_stars == 1 else "stars"
    repo_summary = _esc(f"{metrics.public_repos} public {repo_label} · {metrics.total_stars} {star_label}")
    last_act = _esc(f"LAST ACTIVITY · {metrics.last_activity_date}")
    peak_label = _esc(f"PEAK {metrics.max_week}/WK")

    total_str = _esc(f"{metrics.total_contributions:,}")
    commits_str = _esc(f"{metrics.commits:,}")
    prs_str = _esc(f"{metrics.pull_requests:,}")
    issues_str = _esc(f"{metrics.issues:,}")
    reviews_str = _esc(f"{metrics.reviews:,}")

    cadence_bars = _render_cadence_bars(metrics, theme)
    lang_block = _render_language_bar_and_legend(metrics, theme)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="264" viewBox="0 0 1200 264" role="img" aria-labelledby="title desc">
  <title id="title">GitHub Engineering Telemetry</title>
  <desc id="desc">Self-hosted 12-month contribution ledger, 12-week cadence, and owned repository language mix.</desc>
  <defs>
    <linearGradient id="telemetryBg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{theme.bg_start}"/>
      <stop offset="100%" stop-color="{theme.bg_end}"/>
    </linearGradient>
    <clipPath id="langClip">
      <rect x="822" y="102" width="342" height="8" rx="4"/>
    </clipPath>
  </defs>

  <rect x="0.5" y="0.5" width="1199" height="263" rx="6" fill="url(#telemetryBg)" stroke="{theme.border}" stroke-opacity="{theme.border_opacity}"/>

  <!-- Top bar -->
  <rect x="36" y="23" width="16" height="2" rx="1" fill="{theme.accent_gold}"/>
  <text x="62" y="28" font-family="{FONT_MONO}" font-size="11" font-weight="500" letter-spacing="2.2" fill="{theme.text_secondary}">GITHUB TELEMETRY &#183; 12-MONTH WINDOW</text>
  <text x="1164" y="28" text-anchor="end" font-family="{FONT_MONO}" font-size="11" font-weight="500" letter-spacing="1.4" fill="{theme.text_muted}">{last_act}</text>
  <line x1="0" y1="46" x2="1200" y2="46" stroke="{theme.hairline}" stroke-opacity="{theme.hairline_opacity}"/>

  <!-- 3-Column Swiss grid dividers -->
  <line x1="410" y1="64" x2="410" y2="242" stroke="{theme.hairline}" stroke-opacity="{theme.hairline_opacity}"/>
  <line x1="790" y1="64" x2="790" y2="242" stroke="{theme.hairline}" stroke-opacity="{theme.hairline_opacity}"/>

  <!-- Column 1: Contribution Ledger -->
  <text x="36" y="114" font-family="{FONT_SERIF}" font-size="48" font-weight="400" letter-spacing="-1" fill="{theme.text_primary}">{total_str}</text>
  <text x="36" y="136" font-family="{FONT_SANS}" font-size="12" font-weight="400" fill="{theme.text_muted}">contributions across the last 12 months</text>

  <line x1="36" y1="198" x2="380" y2="198" stroke="{theme.hairline}" stroke-opacity="{theme.hairline_opacity}"/>

  <text x="36" y="180" font-family="{FONT_SANS}" font-size="12" font-weight="500" fill="{theme.text_secondary}">Commits</text>
  <text x="190" y="180" text-anchor="end" font-family="{FONT_MONO}" font-size="14" font-weight="600" fill="{theme.text_primary}">{commits_str}</text>
  <text x="214" y="180" font-family="{FONT_SANS}" font-size="12" font-weight="500" fill="{theme.text_secondary}">Pull Requests</text>
  <text x="380" y="180" text-anchor="end" font-family="{FONT_MONO}" font-size="14" font-weight="600" fill="{theme.text_primary}">{prs_str}</text>

  <text x="36" y="222" font-family="{FONT_SANS}" font-size="12" font-weight="500" fill="{theme.text_secondary}">Issues</text>
  <text x="190" y="222" text-anchor="end" font-family="{FONT_MONO}" font-size="14" font-weight="600" fill="{theme.text_primary}">{issues_str}</text>
  <text x="214" y="222" font-family="{FONT_SANS}" font-size="12" font-weight="500" fill="{theme.text_secondary}">Reviews</text>
  <text x="380" y="222" text-anchor="end" font-family="{FONT_MONO}" font-size="14" font-weight="600" fill="{theme.text_primary}">{reviews_str}</text>

  <!-- Column 2: 12-Week Cadence -->
  <text x="442" y="82" font-family="{FONT_MONO}" font-size="10" font-weight="600" letter-spacing="2" fill="{theme.text_secondary}">12-WEEK CADENCE</text>
  <text x="758" y="82" text-anchor="end" font-family="{FONT_MONO}" font-size="10" font-weight="500" letter-spacing="1.4" fill="{theme.accent_gold}">{peak_label}</text>
{cadence_bars}
  <line x1="442" y1="196" x2="758" y2="196" stroke="{theme.hairline}" stroke-opacity="{theme.hairline_opacity}"/>
  <text x="442" y="226" font-family="{FONT_SANS}" font-size="12" font-weight="400" fill="{theme.text_muted}">{repo_summary}</text>

  <!-- Column 3: Language Mix -->
  <text x="822" y="82" font-family="{FONT_MONO}" font-size="10" font-weight="600" letter-spacing="2" fill="{theme.text_secondary}">LANGUAGE MIX</text>
  <text x="1164" y="82" text-anchor="end" font-family="{FONT_MONO}" font-size="10" font-weight="500" letter-spacing="1.4" fill="{theme.text_muted}">OWNED REPOS</text>
{lang_block}
</svg>
"""


def main() -> int:
    username = os.environ.get("GITHUB_USERNAME", "dilmurodmuxsinjonov").strip()
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if not token:
        print(
            "Error: GITHUB_TOKEN or GH_TOKEN environment variable is required.",
            file=sys.stderr,
        )
        return 1

    user = fetch_github_telemetry(username, token)
    metrics = aggregate_metrics(user)

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for theme_key, theme in THEMES.items():
        output_path = ASSETS_DIR / f"telemetry-{theme_key}.svg"
        svg_content = render_telemetry_svg(metrics, theme)
        output_path.write_text(svg_content, encoding="utf-8", newline="\n")
        ET.parse(output_path)

    print(
        f"Generated telemetry SVGs for {username}: "
        f"{metrics.total_contributions} contributions, "
        f"{metrics.public_repos} public repos, "
        f"last activity {metrics.last_activity_date}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
