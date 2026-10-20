"""Build site/ from web/, the script and the agent prompt.

Run after any change: python3 build.py. The Docker image runs it too.
"""

import html
import shutil
from pathlib import Path

root = Path(__file__).parent
site = root / "site"
shutil.rmtree(site, ignore_errors=True)
shutil.copytree(root / "web", site)

page = site / "index.html"
text = page.read_text()
for marker, source in {"@@SCRIPT@@": "oracle-free-server.py", "@@PROMPT@@": "agent-prompt.md"}.items():
    if text.count(marker) != 1:
        raise SystemExit(f"web/index.html must hold exactly one {marker} marker.")
    text = text.replace(marker, html.escape((root / source).read_text(), quote=False))
    shutil.copy(root / source, site / source)
page.write_text(text)
print(f"built {site}")
