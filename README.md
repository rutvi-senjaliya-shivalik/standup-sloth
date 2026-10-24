# Standup Sloth 🦥

**Your daily standup, written by a local open-weight model while you sip chai.**

Standup Sloth reads yesterday's git commits and your unfinished changes, hands them to **Gemma running locally through Ollama**, and gives you a clean *Yesterday / Today / Blockers* update. It can run itself every weekday morning, copy the result to your clipboard, and ping you with a notification.

Your code and commit messages never leave your machine. No API key, no account, no bill.

```
$ python3 standup_sloth.py --scan ~/Projects --copy

**Yesterday**
- [shop-app] Fixed login crash on Android 14
- [shop-api] Added pagination to the orders endpoint

**Today**
- [shop-app] Finish the cart screen redesign

**Blockers**
- None

— Written by gemma3:4b locally in 6.1s · cost: ₹0 · bytes sent to the cloud: 0
📋 Copied to clipboard.
```

## Setup (5 minutes)

1. Install [Ollama](https://ollama.com) and pull Gemma:
   ```bash
   ollama pull gemma3:4b
   ```
2. Get the script (Python 3.8+, no dependencies):
   ```bash
   git clone https://github.com/rutvi-senjaliya-shivalik/standup-sloth.git
   cd standup-sloth
   ```

## Usage

| Command | What it does |
|---|---|
| `python3 standup_sloth.py` | Standup for the repo you're in |
| `python3 standup_sloth.py ~/work/app ~/work/api` | Several repos at once |
| `python3 standup_sloth.py --scan ~/Projects` | Every git repo inside a folder |
| `--copy` | Copy the result to the clipboard (macOS) |
| `--dry-run` | Show exactly what the model will see, then stop |
| `--everyone` | Include teammates' commits, not just yours |
| `--model qwen2.5:3b` | Swap in any Ollama model |
| `--schedule 09:30` | Run every weekday at 09:30, copy + notify (macOS) |
| `--unschedule` | Remove the schedule |

On Monday it automatically looks back to Friday. Every standup is saved to `~/.standup-sloth/history/`.

## How it works

1. `git log --all --since=<last working day> --author=<you>` in each repo, plus `git diff --shortstat` for unfinished work.
2. That activity is sent to `http://localhost:11434/api/chat` with a strict prompt: use only the facts, group related commits, never invent work.
3. If `OLLAMA_HOST` ever points somewhere other than your own machine, the sloth warns you before anything is sent.

## License

MIT
