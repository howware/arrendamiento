"""Install this howware's skill into an agent host.

    python tools/install_skill.py                                   # ~/.claude/skills/<name>
    python tools/install_skill.py --target ~/.codex/skills/<name>   # Codex

Copies skill/<name>/. Reinstalling replaces the skill and never touches the owner's data.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    manifest = json.loads((ROOT / "howware.json").read_text(encoding="utf-8"))
    name, source = manifest["name"], ROOT / manifest["skill"]
    parser = argparse.ArgumentParser(description=f"Install the {name} skill")
    parser.add_argument("--target", default=str(Path.home() / ".claude" / "skills" / name))
    target = Path(parser.parse_args().target).expanduser()
    if target.name != name:
        print(f"The target folder must be named {name}: {target}", file=sys.stderr)
        return 2
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"Installed {name} {manifest['version']} in {target}")
    for kind, items in (("adapter", manifest.get("adapters", [])), ("requirement", manifest.get("requires", []))):
        for item in items:
            print(f"Also needs {kind} {item['name']} {item['version']}: {item.get('url', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
