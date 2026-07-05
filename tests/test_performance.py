"""Startup benchmark substantiating the lazy-loading gain (pytest-benchmark).

The gain lazy loading claims is *deferred imports*: not importing router modules
until a request needs them. It only materialises when imports are actually
deferred — which the default (Plain) extractor does not do (it imports every
module at load() to read its routes), but a warm Cached extractor does (it reads
routes from the cache file and imports nothing at startup). This is exactly the
nuance issue #1 is about.

Each benchmark builds an app over a package of import-heavy router modules under
one strategy. Python caches imports in ``sys.modules``, so the deferred-import
cost would only be paid on the first round; the ``setup`` callback purges the
package from ``sys.modules`` before every round so each measured build re-pays
(or re-defers) the imports.

- ``eager``  imports and mounts every module (baseline);
- ``plain``  lazy middleware + Plain extractor — still imports every module at
             load(), so it shows no real gain over eager;
- ``cached`` lazy middleware + warm Cached extractor — imports nothing at
             startup, so it is dramatically faster.

``TestStartupGate`` turns the same measurement into the pipeline gate.
"""

import importlib
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import MakePackage
from fastapi import FastAPI

from fastapi_router_lazy import (
    AbstractRouteInfosExtractor,
    CachedRouteInfosExtractor,
    RouterLoader,
    lazy_middleware_factory,
    route_infos_extractor,
)

_N_MODULES = 40
_IMPORT_MS = 10
_ROUNDS = 3

# Cached defers all router imports, so its startup must beat eager by at least
# this factor. The ratio compares two builds on the same machine, so a slower
# runner only inflates it (import cost dominates even more). It stays
# timing-dependent, hence the timing_sensitive marker for quarantine.
_REQUIRED_SPEEDUP = 3.0

_HEAVY_ROUTER = """
import time

time.sleep({sleep!r})  # simulate a heavy import-time cost

from fastapi import APIRouter

router = APIRouter()


@router.get("/m{index}")
def endpoint() -> int:
    return {index}
"""


class BenchPackage:
    def __init__(self, package: str, cache_file: Path) -> None:
        self.package = package
        self.module_names = [f"{package}.m{i}.router" for i in range(_N_MODULES)]
        self.cache_file = cache_file

    def purge(self) -> None:
        """Drop the package from sys.modules so a later build re-imports it."""
        for name in list(sys.modules):
            if name == self.package or name.startswith(f"{self.package}."):
                del sys.modules[name]
        CachedRouteInfosExtractor.clear_file_cache()

    def build_eager(self) -> FastAPI:
        app = FastAPI()
        for name in self.module_names:
            module: Any = importlib.import_module(name)
            app.include_router(module.router)
        return app

    def _build_lazy(self, extractor: AbstractRouteInfosExtractor) -> FastAPI:
        app = FastAPI()
        loader = RouterLoader(extractor, app)
        middleware = lazy_middleware_factory(loader)
        app.add_middleware(middleware)
        loader.load(middleware)
        return app

    def build_plain(self) -> FastAPI:
        return self._build_lazy(route_infos_extractor(self.package))

    def build_cached(self) -> FastAPI:
        return self._build_lazy(
            route_infos_extractor(self.package, cache=True, cache_file=self.cache_file)
        )


@pytest.fixture
def bench_package(make_package: MakePackage, tmp_path: Path) -> BenchPackage:
    sources = {
        f"m{i}.router": _HEAVY_ROUTER.format(sleep=_IMPORT_MS / 1000, index=i)
        for i in range(_N_MODULES)
    }
    package = BenchPackage(make_package(sources), tmp_path / "routes.json")
    # Warm the cache once (imports every module a single time), then start clean.
    route_infos_extractor(package.package, cache=True, cache_file=package.cache_file)
    package.purge()
    return package


@pytest.mark.benchmark(group="startup")
class TestStartupBenchmark:
    def _run(
        self, benchmark: Any, build: Callable[[], FastAPI], purge: Callable[[], None]
    ) -> None:
        benchmark.pedantic(build, setup=purge, rounds=_ROUNDS, iterations=1)

    def test_eager(self, benchmark: Any, bench_package: BenchPackage) -> None:
        self._run(benchmark, bench_package.build_eager, bench_package.purge)

    def test_plain_lazy(self, benchmark: Any, bench_package: BenchPackage) -> None:
        self._run(benchmark, bench_package.build_plain, bench_package.purge)

    def test_cached_lazy(self, benchmark: Any, bench_package: BenchPackage) -> None:
        self._run(benchmark, bench_package.build_cached, bench_package.purge)


@pytest.mark.benchmark
@pytest.mark.timing_sensitive
class TestStartupGate:
    @staticmethod
    def _best(build: Callable[[], FastAPI], purge: Callable[[], None]) -> float:
        times: list[float] = []
        for _ in range(_ROUNDS):
            purge()
            start = time.perf_counter()
            build()
            times.append(time.perf_counter() - start)
        return min(times)

    def test_cache_defers_imports_and_speeds_startup(
        self, bench_package: BenchPackage
    ) -> None:
        eager = self._best(bench_package.build_eager, bench_package.purge)
        plain = self._best(bench_package.build_plain, bench_package.purge)
        cached = self._best(bench_package.build_cached, bench_package.purge)

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
