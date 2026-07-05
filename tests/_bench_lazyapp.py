"""Import-heavy router package + app builder for the startup benchmark.

Run as a module (``python -m _bench_lazyapp``); it generates a package of
router modules whose import is artificially costly, builds a FastAPI app under
the selected strategy, and prints the build time in seconds on the last line.

Framework imports (fastapi, fastapi_router_lazy) happen before timing starts, so
the printed number isolates the per-strategy startup cost — dominated by whether
the router modules are imported at startup or deferred.

Env:
  BENCH_PKG_DIR     directory holding the generated package (created if absent);
                    must stay identical across the cache warmup and the measured
                    runs so module names and checksums line up
  BENCH_N_MODULES   number of router modules (default 50)
  BENCH_IMPORT_MS   artificial import cost per module, milliseconds (default 20)
  BENCH_MODE        "eager" | "plain" | "cached"
  BENCH_CACHE_FILE  routes.json path (used by "cached" mode)
"""

import importlib
import os
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from fastapi_router_lazy import (
    RouterLoader,
    lazy_middleware_factory,
    route_infos_extractor,
)

_PKG = "bench_routers"
_N_MODULES = int(os.environ.get("BENCH_N_MODULES", "50"))
_IMPORT_MS = int(os.environ.get("BENCH_IMPORT_MS", "20"))
_MODE = os.environ.get("BENCH_MODE", "cached")
_PKG_DIR = Path(os.environ["BENCH_PKG_DIR"])
_CACHE_FILE = Path(os.environ.get("BENCH_CACHE_FILE", _PKG_DIR / "routes.json"))

_MODULE_TEMPLATE = """
import time

time.sleep({import_seconds!r})  # simulate a heavy import-time cost

from fastapi import APIRouter

router = APIRouter()


@router.get("/m{index}")
def endpoint() -> int:
    return {index}
"""


def _ensure_package() -> None:
    """Generate the router package on disk (idempotent) and make it importable."""
    root = _PKG_DIR / _PKG
    if not root.exists():
        root.mkdir(parents=True)
        (root / "__init__.py").write_text("")
        for index in range(_N_MODULES):
            module_dir = root / f"m{index}"
            module_dir.mkdir()
            (module_dir / "__init__.py").write_text("")
            (module_dir / "router.py").write_text(
                textwrap.dedent(
                    _MODULE_TEMPLATE.format(
                        import_seconds=_IMPORT_MS / 1000, index=index
                    )
                )
            )

    if str(_PKG_DIR) not in sys.path:
        sys.path.insert(0, str(_PKG_DIR))


def _build_app() -> FastAPI:
    """Build the app under the selected strategy. Assumes the package exists."""
    app = FastAPI()

    if _MODE == "eager":
        for index in range(_N_MODULES):
            module: Any = importlib.import_module(f"{_PKG}.m{index}.router")
            app.include_router(module.router)
    else:
        if _MODE == "cached":
            extractor = route_infos_extractor(_PKG, cache=True, cache_file=_CACHE_FILE)
        else:
            extractor = route_infos_extractor(_PKG)
        loader = RouterLoader(extractor, app)
        middleware = lazy_middleware_factory(loader)
        app.add_middleware(middleware)
        loader.load(middleware)

    return app


if __name__ == "__main__":
    _ensure_package()
    _start = time.perf_counter()
    _build_app()
    print(time.perf_counter() - _start)
