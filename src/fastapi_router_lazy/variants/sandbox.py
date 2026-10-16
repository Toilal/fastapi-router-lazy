"""Subprocess sandbox for the variant-aware extraction (``variants`` extra).

Runs the recording extraction in a child process, so importing the router
modules never touches the parent interpreter. Import-time side effects that
cannot run twice in one interpreter (a global registry refusing duplicates, an
extension built with an old PyO3 refusing a second initialization) run once,
in the child, and the parent's later real import runs them once more, in a
clean ``sys.modules``.

The child imports the ``RouterWrapper`` class from its import path: it must be
defined at module level, outside ``__main__``, and its defaults must be set
when its module is imported, since the child does not see settings applied at
runtime in the parent.
"""

import importlib
import pickle
import sys

from fastapi_router_variants import RouterWrapper

from fastapi_router_lazy.extractors.abc import (
    DEFAULT_ROUTER_MODULE_PATTERN,
    ExtractorDefaultsProtocol,
)
from fastapi_router_lazy.extractors.sandbox import (
    SandboxRouteInfosExtractor,
    run_sandboxed,
)
from fastapi_router_lazy.route_info import ExtractedRouteInfo
from fastapi_router_lazy.variants.extractor import record_module_routes


def router_wrapper_class_path(router_wrapper_class: type[RouterWrapper]) -> str:
    """The ``module:qualname`` path the sandbox child imports the class from."""
    module_name = router_wrapper_class.__module__
    qualname = router_wrapper_class.__qualname__
    if module_name == "__main__" or "<locals>" in qualname:
        raise ValueError(
            f"{module_name}.{qualname} must be importable by the sandbox process: "
            f"define it at module level, outside __main__."
        )
    return f"{module_name}:{qualname}"


def import_router_wrapper_class(path: str) -> type[RouterWrapper]:
    module_name, _, qualname = path.partition(":")
    resolved: object = importlib.import_module(module_name)
    for name in qualname.split("."):
        resolved = getattr(resolved, name)
    if not isinstance(resolved, type) or not issubclass(resolved, RouterWrapper):
        raise TypeError(f"{path} is not a RouterWrapper subclass")
    return resolved


def record_routes_sandboxed(
    router_wrapper_class: type[RouterWrapper],
    modules: list[str],
    python_executable: str = sys.executable,
) -> list[ExtractedRouteInfo]:
    return _record_routes_sandboxed(
        router_wrapper_class_path(router_wrapper_class), modules, python_executable
    )


def _record_routes_sandboxed(
    router_wrapper_class_path: str, modules: list[str], python_executable: str
) -> list[ExtractedRouteInfo]:
    if not modules:
        return []
    return run_sandboxed(
        __name__, [router_wrapper_class_path, *modules], python_executable
    )


class SandboxRecordingRouteInfosExtractor(SandboxRouteInfosExtractor):
    """Extract route metadata under recording mode, in a child process.

    Yields the same route infos as
    :class:`~fastapi_router_lazy.variants.RecordingRouteInfosExtractor`.
    """

    def __init__(
        self,
        router_wrapper_class: type[RouterWrapper],
        package_name: str,
        *,
        router_module_pattern: str = DEFAULT_ROUTER_MODULE_PATTERN,
        defaults: ExtractorDefaultsProtocol | None = None,
        python_executable: str = sys.executable,
    ) -> None:
        self.router_wrapper_class_path = router_wrapper_class_path(router_wrapper_class)
        super().__init__(
            defaults if defaults is not None else router_wrapper_class.defaults,
            package_name,
            router_module_pattern=router_module_pattern,
            python_executable=python_executable,
        )
        self.router_wrapper_class = router_wrapper_class

    def _extract_sandboxed(self, modules: list[str]) -> list[ExtractedRouteInfo]:
        return _record_routes_sandboxed(
            self.router_wrapper_class_path, modules, self.python_executable
        )


if __name__ == "__main__":
    _result_path = sys.argv[1]
    _router_wrapper_class = import_router_wrapper_class(sys.argv[2])
    _result = record_module_routes(_router_wrapper_class, sys.argv[3:])
    with open(_result_path, "wb") as _fp:
        pickle.dump(_result, _fp)
