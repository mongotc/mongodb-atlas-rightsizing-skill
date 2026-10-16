#!/usr/bin/env python3
"""
Dispatch an extraction to both visualization renderers:

  - visualize_old → `visualization_old.html` (overlay dashboard, all metrics)
  - visualize_new → `visualization_new.html` (per-node memory view)

CLI:
  python src/visualize/visualize.py --extraction <path/to/extraction.json>
                                    [--no-open]

Both HTML files are written next to the input extraction.json. Only the
new per-node view auto-opens in the browser; the overlay view is written
silently so you can `open visualization_old.html` to compare.
"""

import argparse
import json
import os
import sys

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

# Bare sibling imports (not `from visualize.X import ...`) because when this
# file runs as a script, the script's own directory (src/visualize/) is on
# sys.path[0], so `visualize_old` and `visualize_new` resolve directly to
# the sibling files. Using the `visualize.` package prefix here would
# conflict with this file's own name.
from visualize_old import visualize as _render_overlay   # noqa: E402
from visualize_new import visualize as _render_per_node  # noqa: E402


_PROJECT_ROOT = os.path.dirname(_SRC_DIR)
DEFAULT_OUT_TEMPLATE = os.path.join(
    _PROJECT_ROOT, os.environ.get("OUTPUT_DIR", "output"), "{cluster}", "extraction.json"
)


def visualize(extraction_path, out=None, open_browser=True):
    """Render BOTH the overlay (visualization_old.html) and the per-node
    (visualization_new.html) HTML files next to extraction.json. Returns
    the tuple (old_path, new_path).

    `out` is accepted for API compatibility with the old single-file
    `visualize()` but is ignored — the two outputs always use fixed
    sibling filenames so a bulk caller doesn't have to disambiguate."""
    base = os.path.dirname(os.path.abspath(extraction_path)) or "."
    old_path = _render_overlay(
        extraction_path=extraction_path,
        out=os.path.join(base, "visualization_old.html"),
        open_browser=False,
    )
    new_path = _render_per_node(
        extraction_path=extraction_path,
        out=os.path.join(base, "visualization_new.html"),
        open_browser=open_browser,
    )
    return old_path, new_path


def console_main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--extraction", required=True,
                    help="Path to extraction.json (from src/extraction/)")
    ap.add_argument("--no-open", action="store_true",
                    help="Do not auto-open the per-node HTML in the default browser")
    args = ap.parse_args(argv)

    try:
        old_path, new_path = visualize(
            extraction_path=args.extraction,
            open_browser=not args.no_open,
        )
    except OSError as e:
        sys.exit(f"Could not read extraction: {e}")
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in extraction: {e}")

    print(f"[written to {old_path}]")
    print(f"[written to {new_path}]")
    return 0


if __name__ == "__main__":
    sys.exit(console_main())
