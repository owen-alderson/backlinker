# Contributing

Bug reports, ideas and pull requests are welcome.

## Reporting a bug

Open an [issue](https://github.com/owen-alderson/backlinker/issues) with:

- what you typed and what landed in the note (or what you expected)
- whether it was the CLI (`bl --version`) or the Obsidian plugin (version from *Community plugins*)
- your OS, and your daily-note folder and date format if the note went to the wrong place

A wrong link or a missed link is the most useful report: please include the note names involved.

## Changing the code

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
cd plugin && npm ci && npm test && npm run build
```

- Linking rules live twice, in `backlinker/linker.py` and `plugin/src/linker.ts`. Change both, and add a case to [spec/linker-cases.json](spec/linker-cases.json) so both test suites check it.
- Tests use temporary vaults only. Nothing should touch a real vault or the network.
- Keep the core free of dependencies and free of AI or network calls.

Open the pull request against `main` with a short note on what changed and why. CI runs both test suites.
