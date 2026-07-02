"""Subprocess sandbox extractor (advanced, optional).

Isolates the module imports in a child process so their (potentially heavy)
import-time side effects never touch the parent interpreter. The child imports
each module, reads the routes off its FastAPI routers, and pickles the results
back. Needs nothing but FastAPI.
"""

import logging
import os
import pickle
import subprocess
import sys
from typing import cast

from fastapi_router_lazy.extractors.abc import (
    DEFAULT_ROUTER_MODULE_PATTERN,
    AbstractRouteInfosExtractor,
    CachedExtractedRouteInfos,
    ExtractorDefaultsProtocol,
    InitializableExtractor,
)
from fastapi_router_lazy.extractors.plain import extract_routes_from_module
from fastapi_router_lazy.route_info import ExtractedRouteInfo

logger = logging.getLogger(__name__)


def extract_routes_sandboxed(
    modules: list[str], python_executable: str = sys.executable
) -> list[ExtractedRouteInfo]:
    if not modules:
        return []

    # Propagate the parent's import path so the child resolves the same modules.
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    entries = [p for p in sys.path if p]
    if existing:
        entries.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(entries)

    process = subprocess.run(
        [python_executable, "-m", __name__, *modules],
        capture_output=True,
        env=env,
    )

    if process.returncode != 0:
        raise RuntimeError(
            f"Sandbox process exited with code {process.returncode}\n"
            f"{process.stderr.decode()}"
        )

    return cast("list[ExtractedRouteInfo]", pickle.loads(process.stdout))


class SandboxRouteInfosExtractor(AbstractRouteInfosExtractor, InitializableExtractor):
    def __init__(
        self,
        defaults: ExtractorDefaultsProtocol,
        package_name: str,
        *,
        router_module_pattern: str = DEFAULT_ROUTER_MODULE_PATTERN,
        python_executable: str = sys.executable,
    ) -> None:
        super().__init__(
            defaults, package_name, router_module_pattern=router_module_pattern
        )
        self.python_executable = python_executable
        self.modules: dict[str, list[ExtractedRouteInfo]] = {}

    def preload_from_cache(self, cache: CachedExtractedRouteInfos) -> None:
        self.modules = {k: list(v) for k, v in cache.routes.items()}

    def reset(self, module_names: set[str] | None = None) -> None:
        if module_names is None:
            self.modules.clear()
        else:
            for module_name in module_names:
                self.modules.pop(module_name, None)

    def init(self) -> None:
        to_extract = [
            module_name
            for module_name in self.scan_router_modules()
            if module_name not in self.modules
        ]
        for route_info in extract_routes_sandboxed(to_extract, self.python_executable):
            self.modules.setdefault(route_info.router_module, []).append(route_info)

    def extract_module_route_infos(
        self,
        module_name: str,
        router_variables: set[str] | None = None,
    ) -> list[ExtractedRouteInfo]:
        route_infos = self.modules.get(module_name)
        if route_infos is None:
            route_infos = extract_routes_sandboxed(
                [module_name], self.python_executable
            )
            self.modules[module_name] = route_infos

        if router_variables is None:
            return route_infos
        return [r for r in route_infos if r.router_variable in router_variables]


if __name__ == "__main__":
    _modules = sys.argv[1:]
    _result: list[ExtractedRouteInfo] = []
    for _module in _modules:
        _result.extend(extract_routes_from_module(_module))
    sys.stdout.buffer.write(pickle.dumps(_result))
