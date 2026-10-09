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


def test_the_setup_hint_works_for_uvx_and_plugin_installs():
    # Plugin and uvx installs have no `whenfree` command on the PATH, so the hint an
    # agent passes on must also give the form that works for them.
    from whenfree import api
    assert "whenfree add" in api.SETUP_HINT and "uvx when-free add" in api.SETUP_HINT


def test_the_skill_keeps_to_when_free_when_no_calendar_is_set_up():
    skill = (ROOT / "skills/when-free/SKILL.md").read_text()
    assert "uvx when-free add" in skill and "do not look for the user's calendar in other tools" in skill


def test_the_skill_offers_a_reply_the_user_can_send():
    skill = (ROOT / "skills/when-free/SKILL.md").read_text()
    assert "ready-to-send reply" in skill and "never offer a time the tool\ndid not return" in skill


def test_the_arguments_the_skill_names_are_the_real_ones():
    from whenfree.agents.tools import REGISTRY
    skill = (ROOT / "skills/when-free/SKILL.md").read_text()
    known = set(REGISTRY["free_slots"].properties)
    for name in ("message", "days", "from", "to", "min_minutes"):
        assert f"`{name}`" in skill and name in known, name
