"""Download the Swiss Ephemeris files required for full precision.

The library falls back to the lower-precision Moshier model when these files
are absent. Review the Swiss Ephemeris licence before shipping:

https://www.astro.com/swisseph/
"""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx

BASE = "https://raw.githubusercontent.com/aloistr/swisseph/master/ephe"
FILES = ("sepl_18.se1", "semo_18.se1")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", type=Path, default=Path(__file__).parents[1] / "ephe")
    args = parser.parse_args()
    args.dest.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=60) as client:
        for name in FILES:
            target = args.dest / name
            if target.exists():
                print(f"skip {name} (already present)")
                continue
            print(f"download {name}")
            response = client.get(f"{BASE}/{name}")
            response.raise_for_status()
            target.write_bytes(response.content)
            print(f"  wrote {target} ({len(response.content) / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
