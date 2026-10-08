"""Build the site into dist/.

    python build.py            # build
    python build.py --serve    # build, then serve at http://localhost:8000
    python build.py --drafts   # include posts marked draft: true
"""

import argparse
import http.server
import shutil
import tomllib
from dataclasses import dataclass
from datetime import date
from functools import partial
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

ROOT = Path(__file__).parent
DIST = ROOT / "dist"


@dataclass(frozen=True)
class Post:
    slug: str
    title: str
    date: date
    summary: str
    draft: bool
    html: Markup


def load_post(path: Path) -> Post:
    """A post is a Markdown file that starts with a `key: value` block between two `---` lines."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path.name}: missing front matter")
    header, body = text[4:].split("\n---\n", 1)
    meta = dict(line.split(":", 1) for line in header.splitlines() if line.strip())
    meta = {key.strip(): value.strip() for key, value in meta.items()}
    for key in ("title", "date", "summary"):
        if key not in meta:
            raise ValueError(f"{path.name}: front matter needs '{key}'")
    html = markdown.markdown(
        body,
        extensions=["fenced_code", "tables", "footnotes", "codehilite"],
        extension_configs={"codehilite": {"guess_lang": False}},
    )
    return Post(
        slug=path.stem,
        title=meta["title"],
        date=date.fromisoformat(meta["date"]),
        summary=meta["summary"],
        draft=meta.get("draft", "false").lower() == "true",
        html=Markup(html),
    )


def build(drafts: bool = False) -> None:
    site = tomllib.loads((ROOT / "site.toml").read_text(encoding="utf-8"))
    posts = [load_post(p) for p in sorted((ROOT / "content" / "posts").glob("*.md"))]
    posts = sorted((p for p in posts if drafts or not p.draft), key=lambda p: p.date, reverse=True)

    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    about = Markup(markdown.markdown((ROOT / "content" / "about.md").read_text(encoding="utf-8")))

    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(ROOT / "static", DIST)

    def render(template: str, out: str, **context: object) -> None:
        target = DIST / out
        target.parent.mkdir(parents=True, exist_ok=True)
        html = env.get_template(template).render(site=site, posts=posts, **context)
        target.write_text(html, encoding="utf-8")

    render("index.html", "index.html", about=about)
    render("404.html", "404.html")
    if posts:
        render("writing.html", "writing/index.html")
        render("feed.xml", "feed.xml")
        for post in posts:
            render("post.html", f"writing/{post.slug}/index.html", post=post)
    print(f"built {len(posts)} post(s) into {DIST}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--drafts", action="store_true")
    args = parser.parse_args()
    build(drafts=args.drafts)
    if args.serve:
        handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))
        print("serving at http://localhost:8000")
        http.server.ThreadingHTTPServer(("localhost", 8000), handler).serve_forever()


if __name__ == "__main__":
    main()
