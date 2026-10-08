# yashbitla.com

My personal site. A small static site: Markdown and TOML in, plain HTML out.

## Run it

```bash
python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python build.py --serve     # http://localhost:8000
```

## Pages

| Page | Template | Shows |
|---|---|---|
| `/` | `templates/index.html` | Introduction, three numbers, current role, project cards, latest posts |
| `/experience/` | `templates/experience.html` | All roles, research, education |
| `/projects/` | `templates/projects.html` | Each project with its findings |
| `/writing/` | `templates/writing.html` | All posts (built when one exists) |

## Change it

| To change | Edit |
|---|---|
| The text at the top of the home page | `content/about.md` |
| Experience, projects, research, education, the three numbers, links | `site.toml` |
| The photo | `static/yash.jpg` (square) |
| Layout | `templates/` |
| Colors and fonts | `static/style.css` |

## Write a post

Add a file to `content/posts/`. The file name becomes the URL: `hybrid-search.md` is served at `/writing/hybrid-search/`.

```markdown
---
title: The title
date: 2026-10-08
summary: One sentence for the post list and link previews.
draft: true
---

The post, in Markdown. Code blocks, tables and footnotes work.
```

A post with `draft: true` is left out of the build. Use `python build.py --serve --drafts` to preview it. The Writing section and the feed appear when the first post is published.

## Deploy

A push to `main` builds the site and publishes it to GitHub Pages (`.github/workflows/deploy.yml`).
