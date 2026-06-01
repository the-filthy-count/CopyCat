# 🐾 CopyCat

A self-hosted web app to **find duplicate videos** and **review them at a glance**.

Point CopyCat at a folder of videos. It queues every file, extracts a **filmstrip**
of evenly-spaced stills so you can see the content without opening anything, and
**groups similar videos together** so duplicates (including re-encodes and resizes,
not just byte-identical copies) are easy to spot and clean up.

## What it does

- **Scan queue** — watches an input folder; new/changed files are processed by a
  background worker (probe → hash → extract stills → fingerprint).
- **Filmstrips** — a row of thumbnails per video; click any still to enlarge.
- **Duplicate detection (hybrid)** —
  - *Exact:* identical files matched by SHA-256.
  - *Near-duplicate:* perceptual frame hashes (pHash) grouped by visual similarity,
    so a 720p original and its 360p re-encode land in the same group.
- **Manage duplicates** — per group, the largest/best copy is highlighted; keep one
  and delete the rest, delete individuals, or mark "not a duplicate".
- **Safe deletes (configurable)** — default moves files to a **trash folder**
  (restorable); switch to permanent delete, and empty the trash when you're sure.

## Quick start

```bash
# Point MEDIA_DIR at your video library (must be writable for trash/delete).
MEDIA_DIR=/path/to/videos docker compose up --build
```

Then open <http://localhost:8080>, click **Scan input folder**, and watch the queue
process. Duplicates appear under **Duplicates**; all videos under **Library**.

If you don't set `MEDIA_DIR`, the bundled `./sample-media` folder is used.

## Configuration

Set via environment in `docker-compose.yml` (all are also editable live on the
**Settings** page):

| Variable | Default | Meaning |
|---|---|---|
| `INPUT_DIR` | `/media` | Folder scanned for videos (container path). |
| `TRASH_DIR` | `<INPUT_DIR>/.copycat-trash` | Where trashed files are moved. |
| `DATA_DIR` | `/data` | SQLite DB + generated thumbnails (persistent volume). |
| `DELETE_MODE` | `trash` | `trash` (reversible) or `permanent`. |
| `FRAMES_PER_STRIP` | `10` | Stills extracted per video. |
| `THUMB_WIDTH` | `240` | Thumbnail width in pixels. |
| `SIMILARITY_THRESHOLD` | `0.15` | 0 = identical only; higher = looser matching. |
| `MATCH_METHOD` | `combined` | `combined`/`phash`/`dhash`/`ahash`/`whash`. |
| `MATCH_IGNORE_DURATION` | `1` | `1` = match regardless of runtime; `0` = length-aware. |
| `DURATION_TOLERANCE` | `2` | Max runtime difference (s); only used when length-aware. |
| `PORT` | `8080` | HTTP port. |

The library is bind-mounted **read-write** because trashing/deleting moves and
removes files. The DB and thumbnails live on the `copycat-data` named volume, so
restarts don't reprocess unchanged files.

## How matching works

Each processed video gets a **multi-signal fingerprint**: for every filmstrip frame
we store four complementary perceptual hashes — **pHash** (structure), **dHash**
(edges/gradients), **aHash** (average), and **wHash** (wavelet). Different hashes are
robust to different distortions, so combining them catches more re-encodes/resizes
than any single one.

Two videos are compared by **best-match** frame alignment: each frame is paired with
its closest counterpart in the other video (in both directions), rather than frame
#1↔#1. This means **trimmed, padded, or offset copies still line up** — a common
reason naïve matchers miss real duplicates.

Configurable on the **Settings → Matching** panel:

- **Method** — `combined` (pHash+dHash, recommended), or a single `phash`/`dhash`/
  `ahash`/`whash`. All four hashes are pre-stored, so switching method **regroups
  instantly** with no reprocessing.
- **Sensitivity (threshold)** — max distance to call two videos duplicates. `0` =
  identical only; higher = looser/more matches. **Raise it (~0.15–0.25) if real
  duplicates are being missed.**
- **Ignore duration** — on: match purely on visual content regardless of runtime
  (catches trimmed/padded copies, compares every pair); off: only compare videos
  with similar runtimes (faster, fewer false positives, gated by *duration tolerance*).

Exact SHA-256 matches are always grouped. **Settings → Maintenance → Recompute
fingerprints** rebuilds hashes from the existing thumbnails (no re-scan) — useful
after upgrading or changing the frame count.

The **Library** lists every video ordered by a nearest-neighbor walk over the
fingerprints, so the most visually similar videos sit next to each other and probable
duplicates cluster together **even when they fall below the grouping threshold** —
each tile shows how similar it is to the previous one.

## Tech

FastAPI + Jinja2 + HTMX, SQLite (SQLModel), ffmpeg/ffprobe, Pillow + imagehash —
all in a single container with one in-process background worker. No external
services required.

## Development (without Docker)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
INPUT_DIR=./sample-media DATA_DIR=./data uvicorn app.main:app --reload --port 8080
```
# CopyCat
