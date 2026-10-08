"""Every place that names the version says the same one, so a release cannot ship mismatched pieces."""
import json
import pathlib
import tomllib

import whenfree

ROOT = pathlib.Path(__file__).parent.parent


def test_one_version_everywhere():
    v = whenfree.__version__
    assert tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"] == v
    assert tomllib.loads((ROOT / "packaging/mcpb/pyproject.toml").read_text())["project"]["version"] == v
    assert json.loads((ROOT / "packaging/mcpb/manifest.json").read_text())["version"] == v
    server = json.loads((ROOT / "server.json").read_text())
    assert server["version"] == v and [p["version"] for p in server["packages"]] == [v]
    assert json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"] == v
    marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
    assert [p["version"] for p in marketplace["plugins"]] == [v]


def test_the_registry_can_verify_the_pypi_package():
    # The MCP registry looks for this line in the README that PyPI shows.
    name = json.loads((ROOT / "server.json").read_text())["name"]
    assert f"mcp-name: {name}" in (ROOT / "README.md").read_text()


def test_the_extension_offers_the_same_tools():
    from whenfree.agents import tools
    manifest = json.loads((ROOT / "packaging/mcpb/manifest.json").read_text())
    assert [t["name"] for t in manifest["tools"]] == [t["name"] for t in tools.TOOLS]
