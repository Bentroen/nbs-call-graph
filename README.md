# nbs-call-graph

Call graph of [Note Block Studio](https://github.com/OpenNBS/NoteBlockStudio)'s GML codebase: a directed graph of functions and object events, plus an interactive map you can open in a browser.

## Rationale

This project is part of my ongoing research into the complexity of Note Block Studio's codebase. The goal is to visualize Note Block Studio's codebase and the entanglement between its functions and components.

For more information, check the [NBS research paper](https://sol.sbc.org.br/index.php/sbcm/article/view/43946).

## Prerequisites

- [Git](https://git-scm.com/)
- [Python 3.10+](https://www.python.org/)
- [uv](https://docs.astral.sh/uv/) (installs the Python dependencies from `pyproject.toml`)

## Run it locally

Clone this repository and install dependencies:

```bash
git clone https://github.com/Bentroen/nbs-call-graph.git
cd nbs-call-graph
uv sync
```

Clone Note Block Studio into `NoteBlockStudio/` at the repo root (that directory is ignored by git):

```bash
git clone https://github.com/OpenNBS/NoteBlockStudio.git NoteBlockStudio
```

Then, collect the graph and build the site:

```bash
uv run python collect.py
uv run python plot.py
```

`collect.py` writes analysis files under `output/`. `plot.py` writes a Graphviz file there too, and the interactive site under `dist/`.

To view the webpage, serve `dist/` with a local server:

```bash
uv run python -m http.server 8000 --directory dist
```

Then open [http://localhost:8000](http://localhost:8000).

### Pin a Note Block Studio version

Check out a tag or commit inside the clone before collecting. The published site uses the latest NBS release unless a ref is pinned in GitHub (see below).

```bash
git -C NoteBlockStudio fetch --tags
git -C NoteBlockStudio checkout v3.11.0
uv run python collect.py
uv run python plot.py
```

A shallow clone of one tag works the same way:

```bash
git clone --branch v3.11.0 --depth 1 https://github.com/OpenNBS/NoteBlockStudio.git NoteBlockStudio
```

### Useful flags

```bash
uv run python collect.py --root NoteBlockStudio --out output
uv run python plot.py --graph output/call_graph.json --out output --web-out dist
uv run python plot.py --root draw_window --no-html   # descendants of one node, DOT only
```

## How the graph is generated

Two scripts do the work. `collect.py` reads GML and writes the graph. `plot.py` turns that graph into a DOT file and the web app.

### 1. Find source files

`collect.py` walks the NBS checkout (default `NoteBlockStudio/`) and keeps every `*.gml` file.

### 2. Parse definitions and calls

`gml_analyze.py` reads each file and blanks comments and string contents first, so text inside them is not treated as code. Newlines stay in place so line numbers still match the original file.

From that stripped source it builds two kinds of nodes:

- **Functions** — every `function name(` definition. The node is the function name. Its size metrics are the span of the function body (`lines`) and how many of those lines still contain code after comments and strings are removed (`code_lines`).
- **Object events** — a `.gml` file under `objects/`, named `ObjectName:Event` (for example `obj_controller:Create_0`). The whole file is one node.

Calls are `name(` occurrences whose `name` is one of those project functions. GameMaker built-ins and other identifiers are ignored. Each call is attributed to the innermost open function, or to the object event when the call sits outside a function. The edge weight is how many times that caller invokes that callee.

If the same function name is defined more than once, the first definition supplies the node's file, line, and size.

### 3. Write the graph

`collect.py` builds a directed [NetworkX](https://networkx.org/) graph and writes:

| File | Contents |
| --- | --- |
| `output/functions.json` | One record per function and object event |
| `output/functions.csv` | The same records as a table |
| `output/call_graph.edgelist` | Caller, callee, and weight |
| `output/call_graph.json` | Nodes (with metrics) and weighted edges |

### 4. Draw the graph

`plot.py` reads `output/call_graph.json`.

- **Graphviz** — `output/call_graph.dot`. Function nodes are blue, object events are orange, and edge thickness follows the call count. Render it with Graphviz if you have it installed, for example `dot -Tsvg output/call_graph.dot -o call_graph.svg`.
- **Interactive site** — `dist/index.html`, `dist/style.css`, `dist/script.js`, and `dist/graph-data.js`. The page uses [vis-network](https://visjs.github.io/vis-network/) for a force-directed layout. Node color is the node's [Louvain](https://en.wikipedia.org/wiki/Louvain_method) community (computed on the undirected graph, edge weights included). Node size grows with lines of code and how many distinct functions it calls. Edges keep the caller's community color. Pass `--root NAME` to keep only that node and everything it reaches.

## GitHub Pages

On every push to `main`, [`.github/workflows/pages.yml`](.github/workflows/pages.yml) checks out this repo and OpenNBS/NoteBlockStudio, runs `collect.py` and `plot.py`, and deploys `dist/`.

1. In the repo settings, set Pages **Source** to **GitHub Actions**.
2. Optionally set a repository variable `NBS_REF` to a tag (for example `v3.11.0`) or commit SHA to pin the NBS source. If unset, the workflow uses the latest release tag.
