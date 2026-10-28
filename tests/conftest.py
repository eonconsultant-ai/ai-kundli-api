import os
from pathlib import Path

from app.services.astro.ephemeris import configure_ephemeris

# Tests call the AI and compute endpoints many times from one client address;
# the burst limiter would reject them before the behaviour under test runs.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

configure_ephemeris(Path(__file__).resolve().parents[1] / "ephe")
