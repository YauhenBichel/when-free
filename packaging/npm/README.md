# when-free

Which days and times am I free? `when-free` reads your calendar feeds and answers with the slots you can
offer. It is a command-line tool and an MCP server, and it runs on your own machine.

This npm package is a **launcher**, for MCP clients and people who start tools with `npx`. when-free itself
is written in Python and lives on [PyPI](https://pypi.org/project/when-free/). The launcher starts the same
version of it with [uv](https://docs.astral.sh/uv/), so **uv must be installed** (pipx also works):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh                                         # macOS, Linux
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"      # Windows
```

Then:

```bash
npx -y when-free demo        # try it with a sample calendar
npx -y when-free mcp         # the MCP server, over stdio
```

```json
{
  "mcpServers": {
    "when-free": { "command": "npx", "args": ["-y", "when-free", "mcp"] }
  }
}
```

If you already have uv, `uvx when-free mcp` does the same with one process fewer.

## What the launcher does

`when-free <arguments>` runs the first of these that exists, with your arguments unchanged:

1. `uvx when-free==<this version> <arguments>`
2. `uv tool run when-free==<this version> <arguments>`
3. `pipx run when-free==<this version> <arguments>`
4. `python3 -m whenfree <arguments>`, only if that Python already has when-free installed

If none exists it prints how to install uv and exits with code 127.

- The npm version and the PyPI version are always the same number.
- Standard input, output and error go straight to the Python process. The launcher writes nothing to
  standard output, so MCP messages pass through untouched.
- Arguments are passed as a list and never through a shell.
- SIGINT, SIGTERM and SIGHUP are passed on, and the exit code is the Python tool's.
- Nothing runs at install time: no `postinstall`, no download. uv fetches the Python package the first
  time you run it.
- Windows: `uvx.exe`, `uv.exe`, `pipx.exe` and `python.exe` are started directly. `.cmd` and `.bat`
  wrappers are not used, because they can only be started through a shell.

Documentation, settings and the list of tools: <https://github.com/YauhenBichel/when-free#readme>

Licence: Apache-2.0.
