#!/usr/bin/env python3
"""
Build-in-public content generator.

What it does on every run:
  1. Looks at commits since the last time this script ran (tracked in
     .buildinpublic/state.json).
  2. Summarizes that work.
  3. Uses Claude (if ANTHROPIC_API_KEY is set) to write a humanized
     LinkedIn post and a punchy X/Twitter post about the progress,
     plus a short README changelog blurb. Falls back to a plain
     template if no API key is present, so this always works for free.
  4. Rewrites the section of README.md between the BUILD-IN-PUBLIC
     markers.
  5. Writes .buildinpublic/issue_title.txt and issue_body.md, which
     the workflow turns into a GitHub Issue for you to review.
  6. Archives the draft under .buildinpublic/drafts/ and updates state.
"""

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path(".buildinpublic/state.json")
DRAFTS_DIR = Path(".buildinpublic/drafts")
README_PATH = Path("README.md")
START_MARKER = "<!-- BUILD-IN-PUBLIC:START -->"
END_MARKER = "<!-- BUILD-IN-PUBLIC:END -->"

REPO = os.environ.get("REPO", "your-repo")
ACTOR = os.environ.get("ACTOR", "you")


def sh(cmd: str) -> str:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"last_sha": None}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def get_commits(last_sha: str | None) -> list[dict]:
    rng = f"{last_sha}..HEAD" if last_sha else "-15"
    log = sh(f'git log {rng} --no-merges --pretty=format:"%H|%s|%an|%ad" --date=short')
    commits = []
    for line in log.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 3)
        if len(parts) == 4:
            sha, subject, author, date = parts
            commits.append({"sha": sha[:7], "subject": subject, "author": author, "date": date})
    return commits


def get_diff_stat(last_sha: str | None) -> str:
    if last_sha:
        return sh(f"git diff --stat {last_sha}..HEAD")
    return sh("git diff --stat HEAD~15..HEAD 2>/dev/null") or sh("git diff --stat HEAD")


def build_context(commits: list[dict], diff_stat: str) -> str:
    lines = [f"Repo: {REPO}", f"Author: {ACTOR}", "", "Commits:"]
    for c in commits:
        lines.append(f"- {c['subject']} ({c['date']})")
    lines.append("")
    lines.append("Diff stat:")
    lines.append(diff_stat or "(no diff stat available)")
    return "\n".join(lines)


def generate_with_claude(context: str) -> dict:
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    prompt = f"""You're helping a solo developer who is "building in public" turn their
latest GitHub commits into: (1) a short README changelog blurb, (2) a LinkedIn
post, and (3) an X/Twitter post.

Voice rules:
- Written like a real person typing, not a press release or an AI.
- Short sentences. Contractions. No corporate buzzwords ("leverage",
  "seamless", "game-changer", "unlock").
- No excessive emoji (max 1-2 total, only if it fits naturally).
- Lead with the human angle (what was hard, what you learned, what changed)
  before the feature list.
- LinkedIn: 3-6 short paragraphs, can end with a light question to invite
  comments. No hashtag spam — 3 relevant hashtags max at the end.
- X/Twitter: under 260 characters, punchy, one clear hook line first.
- Do not invent features, numbers, or results that aren't implied by the
  commits below. Stay grounded in what actually happened.

Here's the recent work:
---
{context}
---

Respond with ONLY valid JSON (no markdown fences, no commentary), with exactly
these keys:
{{
  "readme_summary": "1-3 sentence changelog blurb for a README, past tense",
  "linkedin_post": "the full LinkedIn post text",
  "twitter_post": "the full X/Twitter post text, under 260 chars"
}}"""

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text)


def generate_with_template(commits: list[dict], diff_stat: str) -> dict:
    """No-API-key fallback so this always works for free."""
    subjects = [c["subject"] for c in commits] or ["small fixes and cleanup"]
    headline = subjects[0]
    rest = subjects[1:4]

    readme_summary = f"Shipped: {headline}" + (f" (+{len(rest)} more changes)" if rest else "")

    li_lines = [
        f"Small update from the {REPO.split('/')[-1]} build log.",
        "",
        f"This round: {headline}.",
    ]
    if rest:
        li_lines.append("Also in the mix: " + ", ".join(rest) + ".")
    li_lines += [
        "",
        "Building this in the open — mistakes, detours, and all.",
        "",
        "What would you want to see next?",
        "",
        "#buildinpublic #indiehackers #softwaredevelopment",
    ]

    tw = f"Shipped: {headline[:180]} — building this one in public. 🛠️"
    if len(tw) > 260:
        tw = tw[:257] + "..."

    return {"readme_summary": readme_summary, "linkedin_post": "\n".join(li_lines), "twitter_post": tw}


def update_readme(readme_summary: str, date_str: str) -> None:
    if not README_PATH.exists():
        README_PATH.write_text(f"# {REPO.split('/')[-1]}\n\n{START_MARKER}\n{END_MARKER}\n", encoding="utf-8")

    content = README_PATH.read_text(encoding="utf-8")
    entry = f"- **{date_str}** — {readme_summary}"

    if START_MARKER in content and END_MARKER in content:
        pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL)
        existing = pattern.search(content).group(0)
        inner = existing[len(START_MARKER):-len(END_MARKER)].strip()
        # Keep the log, newest entry on top, cap at 15 shown entries.
        prior_lines = [l for l in inner.splitlines() if l.strip().startswith("- **")]
        new_inner = "\n".join([entry] + prior_lines[:14])
        replacement = f"{START_MARKER}\n### 🔨 Build Log\n\n{new_inner}\n{END_MARKER}"
        content = pattern.sub(replacement, content)
    else:
        content += f"\n\n{START_MARKER}\n### 🔨 Build Log\n\n{entry}\n{END_MARKER}\n"

    README_PATH.write_text(content, encoding="utf-8")


def write_issue(drafts: dict, date_str: str, commits: list[dict]) -> None:
    title = f"📝 Build-in-public drafts — {date_str}"
    Path(".buildinpublic/issue_title.txt").write_text(title, encoding="utf-8")

    commit_list = "\n".join(f"- `{c['sha']}` {c['subject']}" for c in commits) or "_(no new commits detected)_"

    body = f"""## Review before posting

These drafts were auto-generated from your latest commits. Nothing has been
posted anywhere — copy whichever you like into LinkedIn / X yourself.

### Commits covered
{commit_list}

---

### 📎 LinkedIn draft

```
{drafts['linkedin_post']}
```

### 🐦 X / Twitter draft

```
{drafts['twitter_post']}
```

### 📄 README changelog line added

```
{drafts['readme_summary']}
```

---

*Close this issue once you've posted (or skipped) it. Edit the drafts freely
before pasting — this is a starting point, not a final copy.*
"""
    Path(".buildinpublic/issue_body.md").write_text(body, encoding="utf-8")


def archive_draft(drafts: dict, date_str: str) -> None:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_date = date_str.replace(":", "-")
    (DRAFTS_DIR / f"draft-{safe_date}.json").write_text(json.dumps(drafts, indent=2), encoding="utf-8")


def main() -> None:
    state = load_state()
    last_sha = state.get("last_sha")

    commits = get_commits(last_sha)
    diff_stat = get_diff_stat(last_sha)

    Path(".buildinpublic").mkdir(exist_ok=True)

    if not commits:
        print("No new commits since last run — nothing to draft.")
        Path(".buildinpublic/has_updates.flag").write_text("false", encoding="utf-8")
        return

    context = build_context(commits, diff_stat)

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            drafts = generate_with_claude(context)
        except Exception as e:  # noqa: BLE001 - fall back rather than fail the whole run
            print(f"Claude generation failed ({e}); falling back to template.")
            drafts = generate_with_template(commits, diff_stat)
    else:
        drafts = generate_with_template(commits, diff_stat)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    update_readme(drafts["readme_summary"], date_str)
    write_issue(drafts, date_str, commits)
    archive_draft(drafts, date_str)

    current_sha = sh("git rev-parse HEAD")
    save_state({"last_sha": current_sha, "last_run": datetime.now(timezone.utc).isoformat()})
    Path(".buildinpublic/has_updates.flag").write_text("true", encoding="utf-8")

    print("Done. README updated, drafts archived, issue content written.")


if __name__ == "__main__":
    main()
