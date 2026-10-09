#!/usr/bin/env bash
# Lint: every "Step 3.N" reference names a step that exists in SKILL.md, and
# each reference doc's title names the SKILL.md step that loads it.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

python3 - "$SKILL_DIR" <<'PY'
import pathlib
import re
import sys

skill_dir = pathlib.Path(sys.argv[1])
skill = (skill_dir / "SKILL.md").read_text()
refs = sorted((skill_dir / "references").glob("*.md"))
errors = []


def step_numbers(text):
    """Expand 'Step 3.5', 'Steps 3.7-3.8', 'Steps 3.7 and 3.8' into minor numbers."""
    for m in re.finditer(r"Steps? 3\.(\d+)(?:\s*(?:–|-|and)\s*3\.(\d+))?", text):
        lo = int(m.group(1))
        hi = int(m.group(2) or lo)
        yield m, range(lo, hi + 1)


# Steps defined by SKILL.md headings, and which references each step loads.
defined = set()
loaded_by = {}
sections = re.split(r"^### ", skill, flags=re.M)
for section in sections[1:]:
    heading = section.splitlines()[0]
    nums = [n for _, r in step_numbers(heading) for n in r]
    defined.update(nums)
    for ref in re.findall(r"references/([\w-]+\.md)", section):
        loaded_by.setdefault(ref, set()).update(nums)

for path in [skill_dir / "SKILL.md", *refs]:
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        for m, nums in step_numbers(line):
            for n in nums:
                if n not in defined:
                    errors.append(f"{path.name}:{lineno}: '{m.group(0)}' is not a step in SKILL.md")

for path in refs:
    title = path.read_text().splitlines()[0]
    title_nums = {n for _, r in step_numbers(title) for n in r}
    expected = loaded_by.get(path.name, set())
    if title_nums and expected and not title_nums & expected:
        errors.append(
            f"{path.name}: title '{title}' does not match the step that loads it "
            f"(Step 3.{', 3.'.join(map(str, sorted(expected)))})"
        )

if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
print("Step reference lint passed.")
PY
