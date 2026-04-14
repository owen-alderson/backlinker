# obsidian-quick-add

CLI tool to add notes to your Obsidian vault instantly from the terminal — without opening the app. Detects people, companies, topics, and efforts mentioned in your text and appends to the right file automatically.

No third-party dependencies. Pure Python stdlib.

## The problem it solves

Opening Obsidian, navigating to the right note, formatting a dated entry, and saving — all to capture a single thought — creates enough friction that ideas get lost. This tool removes that friction.

```bash
note add "Sam mentioned the budget is still pending from Jordan"
#  →  Detected: Sam Lee (person), Jordan Rossi (person)
#  →  Appended to Atlas/People/Sam Lee.md
```

## Commands

```bash
# Auto-detect mentions and route
note add "Text here"

# Explicitly route to a specific note
note person "Sam Lee" "mentioned budget still pending"
note company "Ripple" "launched new institutional product today"
note topic "XRP Ledger" "EVM sidechain surpassed 1M transactions"
note effort "Acme" "completed 5 focus group interviews"

# Add to today's calendar
note calendar "Dinner with Max at 8pm at Nori"

# Dry run — see what would be detected
note scan "Had a call with Sam about the Acme pilot"

# Configure vault path
note config --vault "/path/to/your/Obsidian Vault"
note config --show
```

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/owen-alderson/obsidian-quick-add.git
cd obsidian-quick-add
```

**2. Point it at your vault**
```bash
python3 note.py config --vault "/path/to/your/Obsidian Vault"
```

**3. Add a shell alias** (add to `~/.zshrc` or `~/.bashrc`)
```bash
alias note="python3 /path/to/obsidian-quick-add/note.py"
```

Then reload your shell:
```bash
source ~/.zshrc
```

Now just run `note add "..."` from anywhere.

## How detection works

The tool builds an index of all notes in `Atlas/People`, `Atlas/Companies`, `Atlas/Topics`, and `Efforts`. When you run `note add`, it scores every entry in the index against your text using fuzzy string matching (`difflib.SequenceMatcher`). Matches above 75% confidence are surfaced — if there's only one match it routes automatically; if there are multiple it lets you pick.

## Vault structure expected

```
Your Vault/
├── Atlas/
│   ├── People/       ← person notes
│   ├── Companies/    ← company notes
│   └── Topics/       ← topic notes
├── Efforts/          ← active project notes
└── Calendar/         ← YYYY-MM-DD.md files
```

## Requirements

- Python 3.8+
- No pip installs needed
