"""Run the README's Python examples so the documentation stays correct.

Blocks are run in order in one namespace, the way a reader follows the
guide. Blocks that start with ``# illustration only`` need outside
pieces (a model client, pandas) and are skipped.
"""

import re
from pathlib import Path

import pytest

README = Path(__file__).resolve().parent.parent / "README.md"


def readme_blocks():
    text = README.read_text(encoding="utf-8")
    return [
        block
        for block in re.findall(r"```python\n(.*?)```", text, re.DOTALL)
        if not block.startswith("# illustration only")
    ]


@pytest.mark.skipif(not README.exists(), reason="README.md not available")
def test_readme_examples_run(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # the SQLite example writes knowledge.db
    blocks = readme_blocks()
    assert len(blocks) > 20

    namespace = {}
    for number, block in enumerate(blocks):
        exec(compile(block, f"README.md python block {number}", "exec"), namespace)

    out = capsys.readouterr().out
    assert "['accepted', 'accepted']" in out
    assert "quote not found in the text -> DIED_IN" in out
    assert "Philadelphia contradicted" in out
