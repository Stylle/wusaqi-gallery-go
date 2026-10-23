"""Generate Docker Hub's overview from the canonical repository README."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
text = (root / "README.md").read_text(encoding="utf-8")
base = "https://github.com/Stylle/wusaqi-gallery-go/blob/main/"
text = re.sub(r"\]\(((?:docs/|scripts/)[^)]+|docker-compose(?:\.hub)?\.yml)\)",
              lambda m: "](" + base + m[1] + ")", text)
(root / "docs/dockerhub-description.md").write_text(text, encoding="utf-8")
print("Updated docs/dockerhub-description.md")
