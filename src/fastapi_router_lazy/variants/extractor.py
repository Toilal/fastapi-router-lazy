"""Variant/version-aware extraction (optional ``variants`` extra).

Built on ``fastapi-router-variants``. Instead of importing a module and reading
its already-built routes, this extractor imports it under
``RouterWrapper.recording(...)``: the route decorators become no-ops and every
expanded variant (versions x prefixes x flavors) is reported with its full
metadata (``version``, ``prefix``, ``deployment``, ``hidden``) without ever
building the real routes.

Requires ``pip install fastapi-router-lazy[variants]``.
"""

import importlib
import inspect
import logging
import os
import sys

try:
    import fastapi_router_variants as _frv
    from fastapi_router_variants import RouteRecorder, RouterWrapper, RouteType
except ImportError as exc:  # pragma: no cover - exercised via the extra
    raise ImportError(
        "The variant-aware extractors require the optional 'variants' extra. "
        "Install it with: pip install fastapi-router-lazy[variants]"
    ) from exc

import fastapi_router_lazy as _frl
from fastapi_router_lazy.extractors.abc import (
    DEFAULT_ROUTER_MODULE_PATTERN,
    AbstractRouteInfosExtractor,
    CachedExtractedRouteInfos,
    ExtractorDefaultsProtocol,
    InitializableExtractor,
)
from fastapi_router_lazy.route_info import ExtractedRouteInfo

logger = logging.getLogger(__name__)

_INTERNAL_DIRS = (
    os.path.abspath(os.path.dirname(_frv.__file__)),
    os.path.abspath(os.path.dirname(_frl.__file__)),
)


def _variable_from_frame(
    frame_info: inspect.FrameInfo, instance: object | None
) -> str | None:
    if frame_info.code_context:
        line = frame_info.code_context[0].lstrip()
        if line.startswith("@"):
            return line[1:].split("(", 1)[0].split(".", 1)[0].strip()

    if instance is not None:
        for name, value in frame_info.frame.f_globals.items():
            if value is instance:
                return name

    return None


def _record_origin() -> tuple[str, str] | None:
    """Return ``(module, variable)`` of the router declaring the current route.

    Walks out of the internal frames (this package and fastapi-router-variants)
    to the user frame that applied the decorator; grabs the ``RouterWrapper``
    instance from the internal wrapper frame to resolve the variable name.
    """
    wrapper_instance: object | None = None

    for frame_info in inspect.stack()[1:]:
        path = os.path.abspath(frame_info.filename)
        if path.startswith(_INTERNAL_DIRS):
            if wrapper_instance is None:
                candidate = frame_info.frame.f_locals.get("self")
                if isinstance(candidate, RouterWrapper):
                    wrapper_instance = candidate
            continue

        module = frame_info.frame.f_globals.get("__name__")
        variable = _variable_from_frame(frame_info, wrapper_instance)
        if module is None or variable is None:
            return None
        return module, variable

    return None


class _CollectingRecorder(RouteRecorder):
    def __init__(self) -> None:
        self.collected: list[ExtractedRouteInfo] = []

    def record(
        self,
        *,
        path: str,
        type: RouteType,
        methods: tuple[str, ...] | None,
        version: object,
        prefix: object,
        deployment: str | bool | None,
        hidden: bool,
    ) -> None:
        origin = _record_origin()
        if origin is None:
            logger.warning(f"Could not resolve router origin for route {path}")
            return
        module, variable = origin

        self.collected.append(
            ExtractedRouteInfo(
                path=path,
                type=type,
                methods=methods,
                router_module=module,
                router_variable=variable,
                version=version,
                prefix=prefix,
                deployment=deployment,
                hidden=hidden,
            )
        )


class RecordingRouteInfosExtractor(AbstractRouteInfosExtractor, InitializableExtractor):
    """Extract route metadata by importing modules under recording mode."""

    def __init__(
        self,
        router_wrapper_class: type[RouterWrapper],
        package_name: str,
        *,
        router_module_pattern: str = DEFAULT_ROUTER_MODULE_PATTERN,
        defaults: ExtractorDefaultsProtocol | None = None,
    ) -> None:
        super().__init__(
            defaults if defaults is not None else router_wrapper_class.defaults,
            package_name,
            router_module_pattern=router_module_pattern,
        )
        self.router_wrapper_class = router_wrapper_class
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
        for module_name in self.scan_router_modules():
            if module_name not in self.modules:
                self.modules[module_name] = self._extract(module_name)

    def _extract(self, module_name: str) -> list[ExtractedRouteInfo]:
        recorder = _CollectingRecorder()

        # Import under recording, then restore sys.modules: the recorded import
        # builds no real routes, so any module it (re)loaded must not leak to a
        # later real import (e.g. by the loader).
        before = set(sys.modules)
        sys.modules.pop(module_name, None)
        try:
            with self.router_wrapper_class.recording(recorder):
                importlib.import_module(module_name)
        finally:
            for name in set(sys.modules) - before:
                sys.modules.pop(name, None)
            sys.modules.pop(module_name, None)

        return [r for r in recorder.collected if r.router_module == module_name]

    def extract_module_route_infos(
        self,
        module_name: str,
        router_variables: set[str] | None = None,
    ) -> list[ExtractedRouteInfo]:
        route_infos = self.modules.get(module_name)
        if route_infos is None:
            route_infos = self._extract(module_name)
            self.modules[module_name] = route_infos

        if router_variables is None:
            return route_infos
        return [r for r in route_infos if r.router_variable in router_variables]
