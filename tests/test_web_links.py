"""Every internal link on the site must point somewhere real.

Checked for each page under web/ (hand-written and generated alike):
  * paths  -> a file under web/ or a route declared in app/main.py
  * #ids   -> an element with that id on the target page (static pages only)
  * ?case= -> a stored case file;  &run= -> a stored run
  * the site header is one block of markup shared by every page, with the agreed nav targets
"""
import re
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
PAGES = sorted(WEB.glob("*.html"))
ROUTES = re.findall(r'@app\.get\("([^"]+)"', (ROOT / "app" / "main.py").read_text())
CASES = {p.stem for d in ("data/cases", "data/bench/cases") for p in (ROOT / d).glob("*.json")}
RUNS = {p.stem for p in (ROOT / "runs").glob("*.json")}
DYNAMIC_IDS = {"facts.html", "receipt.html", "replay.html"}  # ids rendered by script, not checkable statically

# the one header every page carries, and where each nav item must go
NAV = {"Home": "/", "Watch": "/#watch", "Facts": "/facts.html?case=DISP-002", "Policy": "/policy.html", "Ops": "/ops.html", "Results": "/report.html"}
HEADERLESS = {"replay.html"}  # full-screen tools without the site header


def links(page: Path):
    text = page.read_text()
    for m in re.finditer(r'(?:href|src)="([^"]*)"', text):
        url = m.group(1)
        if not url or url.startswith(("http", "mailto:", "data:")) or "${" in url:
            continue
        yield url


def route_matches(path: str) -> bool:
    for r in ROUTES:
        pat = "^" + re.sub(r"\{[^}]+\}", r"[^/]+", r) + "$"
        if re.match(pat, path):
            return True
    return False


def ids_in(page: Path):
    return set(re.findall(r'\bid="([^"]+)"', page.read_text()))


def test_every_internal_link_resolves():
    bad = []
    for page in PAGES:
        for url in links(page):
            u = urlsplit(url)
            path = u.path
            target = page if not path else (WEB / path.lstrip("/"))
            if path and not path.startswith("/api/") and not path.startswith("/policy-sources"):
                if not target.exists():
                    bad.append(f"{page.name}: {url} -> no file web/{path.lstrip('/')}")
                    continue
            elif path and not route_matches(path):
                bad.append(f"{page.name}: {url} -> no route {path}")
                continue
            if u.fragment and target.suffix == ".html" and target.name not in DYNAMIC_IDS and u.fragment not in ids_in(target):
                bad.append(f"{page.name}: {url} -> no id=\"{u.fragment}\" on {target.name}")
            q = parse_qs(u.query)
            for c in q.get("case", []):
                if c not in CASES:
                    bad.append(f"{page.name}: {url} -> unknown case {c}")
            for r in q.get("run", []):
                if r not in RUNS:
                    bad.append(f"{page.name}: {url} -> unknown run {r}")
    assert not bad, "\n".join(bad)


def test_site_header_is_shared_and_points_where_agreed():
    blocks = {}
    for page in PAGES:
        if page.name in HEADERLESS:
            continue
        m = re.search(r'<header class="site">.*?</header>', page.read_text(), re.S)
        assert m, f"{page.name} has no shared site header"
        blocks[page.name] = m.group(0)
    assert len(set(blocks.values())) == 1, "site header differs between pages: " + ", ".join(blocks)
    header = next(iter(blocks.values()))
    nav = dict(re.findall(r'<a href="([^"]+)">([^<]+)</a>', header.replace("&amp;", "&")))
    assert {v: k for k, v in nav.items()} == NAV, nav
    assert 'button class="theme"' in header
