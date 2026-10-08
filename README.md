# nbs-call-graph

Call graph of Note Block Studio's GML codebase.

## Setup

```bash
uv sync
```

Clone or checkout [Note Block Studio](https://github.com/OpenNBS/NoteBlockStudio) into `NoteBlockStudio/` at the repo root (that directory is gitignored).

## Collect and plot

```bash
uv run python collect.py
uv run python plot.py
```

Analysis artifacts (`.dot`, graph JSON from `collect.py`) go under `output/`. The interactive site (`index.html`, `style.css`, `script.js`, `graph-data.js`) goes under `dist/`.

## GitHub Pages

On every push to `main`, a workflow builds the site from OpenNBS/NoteBlockStudio and deploys `dist/` to GitHub Pages.

1. In the repo settings, set Pages **Source** to **GitHub Actions**.
2. Optionally set a repository variable `NBS_REF` to a tag (e.g. `v3.11.0`) or commit SHA to pin the NBS source. If unset, the workflow uses the latest release tag.
