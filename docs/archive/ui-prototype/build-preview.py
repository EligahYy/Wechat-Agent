"""Build an offline, single HTML preview without third-party dependencies."""
from pathlib import Path
from html.parser import HTMLParser
import base64
import re

root = Path(__file__).resolve().parent
html = (root / "index.html").read_text()
for name in ("styles.css", "assets/motion.css"):
    css = (root / name).read_text()
    pattern = rf'<link\s+rel="stylesheet"\s+href="{re.escape(name)}"\s*/?>'
    html, count = re.subn(pattern, lambda _: f"<style>\n{css}\n</style>", html)
    assert count == 1, f"Expected one stylesheet link for {name}, found {count}"
for name in ("data.js", "app.js"):
    js = (root / name).read_text().replace("</script", "<\\/script")
    html = html.replace(f'<script src="{name}"></script>', f"<script>\n{js}\n</script>")
motion = (root / "assets/motion.js").read_text().replace("</script", "<\\/script")
html = html.replace('<script type="module" src="assets/motion.js"></script>', f'<script type="module">\n{motion}\n</script>')
for name, mime in (("assets/product.svg", "image/svg+xml"), ("assets/11月备货清单.csv", "text/csv;charset=utf-8")):
    data = base64.b64encode((root / name).read_bytes()).decode()
    html = html.replace(name, f"data:{mime};base64,{data}")
class DependencyCheck(HTMLParser):
    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" or (tag == "link" and attributes.get("rel") == "stylesheet"):
            dependency = attributes.get("src") or attributes.get("href")
            assert not dependency or dependency.startswith("data:"), f"External dependency remains: {dependency}"

DependencyCheck().feed(html)
(root / "preview.html").write_text(html)
print("Built ui-prototype/preview.html")
