"""Generate Docker Hub's overview from the canonical repository README."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
text = (root / "README.md").read_text(encoding="utf-8")
base = "https://github.com/Stylle/wusaqi-gallery-go/blob/main/"
text = re.sub(r"\]\(((?:docs/|scripts/)[^)]+|docker-compose(?:\.hub)?\.yml)\)",
              lambda m: "](" + base + m[1] + ")", text)
# Hub limits the UTF-8 payload to 25,000 bytes, rather than 25,000 characters.
# Keep all deployment/features/privacy content; link to the full development
# instructions when the canonical README is too large for the service.
if len(text.encode("utf-8")) > 24000:
    text = re.sub(r"^## 本地运行和验证\n.*?(?=^## )",
                  "## 本地运行和验证\n\n完整的本地开发、构建和测试步骤见 "
                  "[GitHub README](" + base + "README.md#本地运行和验证)。"
                  "功能与界面验证见 [验收记录](" + base + "docs/qa-review.md)。\n\n",
                  text, flags=re.MULTILINE | re.DOTALL)
if len(text.encode("utf-8")) > 25000:
    raise SystemExit("Docker Hub overview exceeds its 25,000-byte limit")
(root / "docs/dockerhub-description.md").write_text(text, encoding="utf-8")
print("Updated docs/dockerhub-description.md")
