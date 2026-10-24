#!/usr/bin/env python3
"""
Standup Sloth 🦥
Writes your daily standup from your git history using a local open-weight
model (Gemma, via Ollama). Your code and commit messages never leave your machine.

Usage:
  python3 standup_sloth.py                      # current repo
  python3 standup_sloth.py ~/work/app ~/work/api
  python3 standup_sloth.py --scan ~/Projects     # every git repo inside a folder
  python3 standup_sloth.py --dry-run             # show exactly what the model will see
  python3 standup_sloth.py --schedule 09:30 --scan ~/Projects   # do it for me every weekday
  python3 standup_sloth.py --unschedule
"""
import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

VERSION = "1.0.0"
DEFAULT_MODEL = os.environ.get("SLOTH_MODEL", "gemma3:4b")
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = "http://" + OLLAMA_URL
HOME_DIR = Path.home() / ".standup-sloth"
HISTORY_DIR = HOME_DIR / "history"
PLIST_LABEL = "dev.standupsloth.daily"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"
MAX_COMMITS_PER_REPO = 40

SYSTEM_PROMPT = """You write daily standup updates for a software developer.
Rules:
- Use ONLY the facts in the activity log. Never invent work, tickets, or people.
- Group related commits into one bullet. Write in plain language a project manager understands.
- Keep every bullet under 15 words. Mention the project name in brackets, like [app].
- "Today": suggest modest next steps based only on unfinished work (uncommitted changes, WIP/TODO commits). If nothing is unfinished, write "- Pick up the next task".
- "Blockers": only list something if the log clearly shows a problem (revert, failing, blocked). Otherwise write "- None".
Output exactly this markdown and nothing else:

**Yesterday**
- ...

**Today**
- ...

**Blockers**
- ...
"""


# ---------------------------------------------------------------- git helpers
def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def is_repo(path):
    return git(path, "rev-parse", "--is-inside-work-tree") == "true"


def find_repos(folder, depth=2):
    folder = Path(folder).expanduser().resolve()
    found = []
    if (folder / ".git").exists():
        return [folder]
    if depth == 0 or not folder.is_dir():
        return found
    try:
        children = sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith("."))
    except PermissionError:
        return found
    for child in children:
        found.extend(find_repos(child, depth - 1))
    return found


def since_date(today=None):
    """Last working day at 00:00. On Monday this looks back to Friday."""
    today = today or dt.date.today()
    back = {0: 3, 6: 2}.get(today.weekday(), 1)  # Mon -> Fri, Sun -> Fri
    return dt.datetime.combine(today - dt.timedelta(days=back), dt.time.min)


def collect(repo, since, everyone=False):
    name = Path(git(repo, "rev-parse", "--show-toplevel") or repo).name
    args = ["log", "--all", "--no-merges", f"--since={since.isoformat()}",
            "--date=format:%a %H:%M", "--pretty=format:%ad | %s",
            f"-n{MAX_COMMITS_PER_REPO}"]
    if not everyone:
        email = git(repo, "config", "user.email")
        if email:
            args.append(f"--author={email}")
    commits = [c for c in git(repo, *args).splitlines() if c.strip()]
    branch = git(repo, "branch", "--show-current") or "(detached)"
    wip = git(repo, "diff", "HEAD", "--shortstat")
    wip_files = git(repo, "diff", "HEAD", "--name-only").splitlines()[:8]
    untracked = git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    return {"name": name, "branch": branch, "commits": commits,
            "wip": wip, "wip_files": wip_files, "untracked": len(untracked)}


def activity_text(items, since):
    lines = [f"Activity since {since:%A %d %b %Y}:"]
    for it in items:
        if not it["commits"] and not it["wip"] and not it["untracked"]:
            continue
        lines.append(f"\n## Project [{it['name']}] (branch: {it['branch']})")
        if it["commits"]:
            lines.append("Commits:")
            lines += [f"- {c}" for c in it["commits"]]
        if it["wip"] or it["untracked"]:
            lines.append("Unfinished work (not committed yet):")
            if it["wip"]:
                lines.append(f"- {it['wip']}")
                lines += [f"  - {f}" for f in it["wip_files"]]
            if it["untracked"]:
                lines.append(f"- {it['untracked']} new untracked file(s)")
    return "\n".join(lines) if len(lines) > 1 else ""


# ------------------------------------------------------------- model helpers
def check_local(url):
    host = urlparse(url).hostname or ""
    if host not in ("localhost", "127.0.0.1", "::1"):
        print(f"⚠️  OLLAMA_HOST points to '{host}', not this machine. "
              "Your commit messages would leave your laptop.", file=sys.stderr)


def ask_model(model, activity):
    body = json.dumps({
        "model": model,
        "stream": False,
        "options": {"temperature": 0.3},
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": activity}],
    }).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            sys.exit(f"🦥 Model '{model}' isn't downloaded yet. Run:  ollama pull {model}")
        sys.exit(f"🦥 Ollama returned an error ({e.code}): {e.read().decode(errors='ignore')}")
    except urllib.error.URLError:
        sys.exit("🦥 Can't reach Ollama. Open the Ollama app (or run `ollama serve`) and try again.")
    return data["message"]["content"].strip(), data


# -------------------------------------------------------------- mac extras
def copy_to_clipboard(text):
    if platform.system() == "Darwin":
        subprocess.run(["pbcopy"], input=text, text=True)
        return True
    return False


def notify(title, message):
    if platform.system() == "Darwin":
        safe = message.replace('"', "'")[:200]
        subprocess.run(["osascript", "-e",
                        f'display notification "{safe}" with title "{title}" sound name "Glass"'])


def install_schedule(time_str, passthrough):
    if platform.system() != "Darwin":
        sys.exit("Scheduling uses macOS launchd. On Linux, add this to `crontab -e`:\n"
                 f"30 9 * * 1-5 {sys.executable} {Path(__file__).resolve()} --notify")
    hour, minute = (int(x) for x in time_str.split(":"))
    days = "".join(
        f"<dict><key>Weekday</key><integer>{d}</integer>"
        f"<key>Hour</key><integer>{hour}</integer>"
        f"<key>Minute</key><integer>{minute}</integer></dict>" for d in range(1, 6))
    prog = [sys.executable, str(Path(__file__).resolve()), "--copy", "--notify", *passthrough]
    args_xml = "".join(f"<string>{a}</string>" for a in prog)
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{PLIST_LABEL}</string>
<key>ProgramArguments</key><array>{args_xml}</array>
<key>StartCalendarInterval</key><array>{days}</array>
<key>EnvironmentVariables</key><dict><key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string></dict>
<key>StandardOutPath</key><string>{HOME_DIR / 'sloth.log'}</string>
<key>StandardErrorPath</key><string>{HOME_DIR / 'sloth.log'}</string>
</dict></plist>"""
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
    PLIST_PATH.write_text(plist)
    subprocess.run(["launchctl", "load", str(PLIST_PATH)])
    print(f"🦥 Scheduled! Every weekday at {hour:02d}:{minute:02d} your standup will be "
          "written, copied to your clipboard, and announced with a notification.")
    print("   Undo any time with: python3 standup_sloth.py --unschedule")


def remove_schedule():
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
        PLIST_PATH.unlink()
        print("🦥 Schedule removed. The sloth is fully retired.")
    else:
        print("🦥 Nothing scheduled.")


# --------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description="Standup Sloth 🦥: your standup, written locally by Gemma.")
    p.add_argument("repos", nargs="*", help="git repos to read (default: current folder)")
    p.add_argument("--scan", metavar="FOLDER", help="find every git repo inside FOLDER")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    p.add_argument("--everyone", action="store_true", help="include teammates' commits too")
    p.add_argument("--dry-run", action="store_true", help="print what the model would see, then stop")
    p.add_argument("--copy", action="store_true", help="copy the standup to the clipboard (macOS)")
    p.add_argument("--notify", action="store_true", help="show a macOS notification when done")
    p.add_argument("--schedule", metavar="HH:MM", help="run automatically every weekday (macOS)")
    p.add_argument("--unschedule", action="store_true", help="remove the daily schedule")
    p.add_argument("--version", action="version", version=f"Standup Sloth {VERSION}")
    a = p.parse_args()

    if a.unschedule:
        return remove_schedule()

    repos = [Path(r).expanduser().resolve() for r in a.repos]
    if a.scan:
        repos += find_repos(a.scan)
    if not repos:
        repos = [Path.cwd()]
    repos = [r for r in dict.fromkeys(repos) if is_repo(r)]
    if not repos:
        sys.exit("🦥 No git repositories found. Pass a repo path or use --scan ~/Projects")

    if a.schedule:
        passthrough = [str(r) for r in repos] + ["--model", a.model] + (["--everyone"] if a.everyone else [])
        return install_schedule(a.schedule, passthrough)

    since = since_date()
    activity = activity_text([collect(r, since, a.everyone) for r in repos], since)
    if not activity:
        msg = f"No commits or unfinished work since {since:%A}. Even the sloth is impressed. 🦥"
        print(msg)
        if a.notify:
            notify("Standup Sloth 🦥", msg)
        return

    if a.dry_run:
        print("──── This is everything the local model will see ────\n")
        print(activity)
        return

    check_local(OLLAMA_URL)
    print(f"🦥 Reading {len(repos)} repo(s) and asking {a.model} on this machine…", file=sys.stderr)
    start = time.time()
    standup, raw = ask_model(a.model, activity)
    secs = time.time() - start

    print("\n" + standup + "\n")
    tokens = raw.get("eval_count")
    stats = f"Written by {a.model} locally in {secs:.1f}s"
    if tokens:
        stats += f" · {tokens} tokens"
    stats += " · cost: ₹0 · bytes sent to the cloud: 0"
    print(f"— {stats}", file=sys.stderr)

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    (HISTORY_DIR / f"{dt.date.today()}.md").write_text(standup + "\n")

    if a.copy and copy_to_clipboard(standup):
        print("📋 Copied to clipboard. Paste it into Slack/Teams and go back to your chai.", file=sys.stderr)
    if a.notify:
        notify("Standup Sloth 🦥", "Your standup is ready" + (" and copied!" if a.copy else "."))


if __name__ == "__main__":
    main()
