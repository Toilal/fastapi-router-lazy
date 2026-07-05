"""Serializable descriptions of the routes a module exposes.

These carry just enough information to decide whether and where to mount a
router lazily, without importing the router itself. ``version`` and ``prefix``
are kept opaque (typed ``Any``) so the core stays independent of any particular
versioning scheme; extractors that carry versioning metadata populate them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

RouteType = Literal["http", "websocket"]

DeploymentSpec = str | bool


@dataclass(frozen=True, kw_only=True)
class RouteInfo:
    path: str
    type: RouteType = "http"
    methods: tuple[str, ...] | None = None


@dataclass(frozen=True, kw_only=True)
class ExtractedRouteInfo(RouteInfo):
    router_variable: str
    router_module: str
    version: Any = None
    prefix: Any = None
    deployment: DeploymentSpec | None = None
    hidden: bool = False
    """Internal-only route: served by its deployment but not published.

    Loaders may use it to skip such routes from ingress/consistency checks.
    """

    def build_variant(self, path: str) -> ExtractedRouteInfo:
        """Return a copy of this route info at a different ``path``.

        Public API for variant-aware extractors that derive several stub paths
        (versioned, prefixed, flavored) from one declared route while keeping
        all other metadata intact.
        """
        return ExtractedRouteInfo(
            type=self.type,
            methods=self.methods,
            path=path,
            router_module=self.router_module,
            router_variable=self.router_variable,
            version=self.version,
            prefix=self.prefix,
            deployment=self.deployment,
            hidden=self.hidden,
        )


@dataclass(frozen=True, kw_only=True)
class MetaRouteInfo(RouteInfo):
    """Manually declared route metadata (routes defined outside a router).

    Public API: lets callers describe a route that no scanned ``APIRouter``
    exposes (e.g. a hand-registered endpoint), carrying the same
    version/prefix/deployment metadata as an extracted one.
    """

    router_variable: str
    version: Any = None
    prefix: Any = None
    deployment: DeploymentSpec | None = None
