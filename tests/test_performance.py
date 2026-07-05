"""Startup benchmark substantiating the lazy-loading gain.

The gain lazy loading claims is *deferred imports*: not importing router modules
until a request needs them. It only materialises when imports are actually
deferred — which the default (Plain) extractor does not do (it imports every
module at load() to read its routes), but a warm Cached extractor does (it reads
routes from the cache file and imports nothing at startup). This is exactly the
nuance issue #1 is about.

The gate below spawns a fresh interpreter per strategy on a package of
import-heavy router modules and compares the app-build time:

- ``eager``  imports and mounts every module (baseline);
- ``plain``  lazy middleware + Plain extractor — still imports every module at
             load(), so it must show no real gain over eager;
- ``cached`` lazy middleware + warm Cached extractor — imports nothing at
             startup, so it must be dramatically faster.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_N_MODULES = 50
_IMPORT_MS = 20
_ROUNDS = 2

# Cached defers all router imports, so its startup must beat eager by at least
# this factor. The ratio compares two runs on the same machine, so a slower
# runner only inflates it (import cost dominates even more). It stays
# timing-dependent, hence the timing_sensitive marker for quarantine.
_REQUIRED_SPEEDUP = 3.0


def _measure(mode: str, pkg_dir: Path, cache_file: Path) -> float:
    env = {
        **os.environ,
        "BENCH_MODE": mode,
        "BENCH_PKG_DIR": str(pkg_dir),
        "BENCH_CACHE_FILE": str(cache_file),
        "BENCH_N_MODULES": str(_N_MODULES),
        "BENCH_IMPORT_MS": str(_IMPORT_MS),
    }
    result = subprocess.run(
        [sys.executable, "-m", "_bench_lazyapp"],
        cwd=str(Path(__file__).parent),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"benchmark subprocess failed:\n{result.stderr}")
    return float(result.stdout.strip().splitlines()[-1])


@pytest.mark.benchmark
@pytest.mark.timing_sensitive
class TestStartupGate:
    def test_cache_defers_imports_and_speeds_startup(self, tmp_path: Path) -> None:
        pkg_dir = tmp_path / "pkg"
        cache_file = tmp_path / "routes.json"

        # Warmup: the first cached run generates the package and builds the cache
        # (importing everything once). Discard its timing.
        _measure("cached", pkg_dir, cache_file)
        assert cache_file.exists()

        def best(mode: str) -> float:
            return min(_measure(mode, pkg_dir, cache_file) for _ in range(_ROUNDS))

        eager = best("eager")
        plain = best("plain")
        cached = best("cached")

        detail = (
            f"eager={eager * 1000:.0f}ms "
            f"plain={plain * 1000:.0f}ms "
            f"cached={cached * 1000:.0f}ms"
        )

        # A warm cache defers every import → startup is dramatically faster.
        assert eager / cached >= _REQUIRED_SPEEDUP, (
            f"cached speedup {eager / cached:.1f}x < {_REQUIRED_SPEEDUP}x ({detail})"
        )

        # The default (Plain) extractor imports every module at load(), so it
        # gives no comparable startup gain — the point of issue #1.
        assert eager / plain < _REQUIRED_SPEEDUP, (
            f"Plain unexpectedly sped startup up {eager / plain:.1f}x ({detail})"
        )
