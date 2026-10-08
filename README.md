# yashbitla.com

My personal site. A small static site: Markdown and TOML in, plain HTML out.

## Run it

```bash
python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python build.py --serve     # http://localhost:8000, rebuilds when a file changes
```

## Change it

| To change | Edit |
|---|---|
| The text at the top of the home page | `content/about.md` |
| Experience, projects, research, education, links | `site.toml` |
| The photo | `static/yash.jpg` (square) |
| Layout | `templates/` |
| Colors and fonts | `static/style.css` |

## Add a project

Add a `[[projects]]` block to `site.toml`, above the others, and put its image in `static/img/`:

```toml
[[projects]]
name = "Project name"
image = "/img/project.png"
image_alt = "What the image shows"
image_fit = "cover"            # or "contain" for a chart that must not be cropped
url = "https://github.com/yash-bitla/project"
summary = "What it is, in one or two sentences."
result = "The main measured result."
stack = "Python · Tool · Tool"
```

The grid adjusts to the number of projects. The home page shows the first 6. With more than 6, the site also builds `/projects/` with the full list.

## Write a post

Add a file to `content/posts/`. The file name becomes the URL: `hybrid-search.md` is served at `/blog/hybrid-search/`.

```markdown
---
title: The title
date: 2026-10-08
summary: One sentence for the post list and link previews.
category: Engineering        # or Personal. The label appears next to the date.
draft: true
---

The post, in Markdown. Code blocks, tables and footnotes work.
```

A post with `draft: true` is left out of the build. Use `python build.py --serve --drafts` to preview it. The Blog section and the feed appear when the first post is published.

## Deploy

A push to `main` builds the site and publishes it to GitHub Pages (`.github/workflows/deploy.yml`).
