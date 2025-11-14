# Repository Guidelines

## Project Structure & Module Organization
Automation lives in single-purpose Python entry points at the repo root: `auto_srt.py` pulls scripts from Notion into `.srt`, `generate_suggestions.py` produces prompts via OpenAI, `generate_images.py` captures ImageFX renders, and `make_and_render.py` stitches timelines into MP4s with OpenCV. Shared state is persisted by `manifesto.py` in the repo root via `manifesto.json`, so keep that file committed to reflect pipeline progress. Raw and intermediate assets are grouped under `output/scripts/` (`srt_outputs/`, `img_suggestions/`, `timelines/`, processed txt), while the drop-in inbox lives at the repo root as `txt_inbox/`. Final frames land in `output/imgs_output/`, and finished edits in `output/videos/`. Prompt templates belong in `prompts/`, browser profiles in `chrome_profiles/` (managed by `create_chrome_profile.py`), and regression tests in `tests/`.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` — isolate dependencies locally.
- `pip install -U openai python-dotenv notion-client playwright opencv-python numpy tqdm` — install the libraries referenced throughout the scripts.
- `python auto_srt.py` → `python generate_suggestions.py base_slug` → `python generate_images.py base_slug` → `python make_and_render.py base_slug` — canonical pipeline, run per base to go from Notion text to rendered video.
- `pytest -q` — execute all tests in `tests/`; add `-k name` when focusing on a stage-specific module.

## Coding Style & Naming Conventions
Follow standard PEP 8 with four-space indents, explicit type hints for new helpers, and descriptive snake_case function names. Keep configuration constants (`SRT_DIR`, `FPS`, `PATTERN_PATH`, etc.) uppercase at the module top, mirroring existing files. When expanding a stage, prefer small pure helpers collocated above the “CORE” block and document non-obvious logic inline with short comments.

## Testing Guidelines
Use `pytest` with filenames shaped like `tests/test_<module>.py`, mirroring the stage you are exercising (e.g., `test_make_and_render.py`). Mock remote services (Notion, OpenAI, Playwright) and store canned payloads under `tests/fixtures/`. Aim for coverage on timing math, manifest mutations, and prompt parsing before submitting automation changes.

## Commit & Pull Request Guidelines
Repository history follows imperative, scope-first messages—stick to Conventional Commit prefixes such as `feat: add timeline merge`, `fix: guard empty SRT blocks`, or `chore: update prompts`. Each pull request should describe the affected pipeline stage, list test evidence (`pytest`, manual run IDs, clip paths), and link the relevant Notion/issue IDs. Include screenshots or short MP4 samples when touching visual output so reviewers can validate rendering deltas quickly.

## Security & Configuration Tips
Store secrets (`OPENAI_API_KEY`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`, optional `OPENAI_MODEL`) in a local `.env`; never commit credentials or downloaded ImageFX cookies. Ensure Chrome profiles inside `chrome_profiles/<name>/Default` remain gitignored and reference them via profile selectors instead of hard-coding paths. Before running Playwright-based scripts, execute `playwright install chromium` inside the venv, and verify the root `manifesto.json` stays writable so automation stages can recover after interruptions.
