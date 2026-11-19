import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
from typing import Protocol

from fastapi_router_lazy.route_info import ExtractedRouteInfo

logger = logging.getLogger(__name__)

DEFAULT_ROUTER_MODULE_PATTERN = "router.py"


class ExtractorDefaultsProtocol(Protocol):
    """Minimal defaults an extractor relies on.

    Any object exposing a ``deployment`` attribute satisfies it structurally.
    """

    deployment: str | None


@dataclass
class ExtractorDefaults:
    deployment: str | None = None


@dataclass(frozen=True)
class RouteSources:
    """Modules a router declares its cached route infos depend on.

    ``error`` says why the declaration is invalid: such a router cannot be
    trusted from the cache outside strict mode.
    """

    modules: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class RouterPriority:
    """Priority a router module declares in the canonical route order.

    ``error`` says why the declaration is invalid; ``value`` is then ``0``.
    """

    value: int = 0
    error: str | None = None


@dataclass
class CachedExtractedRouteInfos:
    router_checksums: dict[str, str]
    routes: dict[str, list[ExtractedRouteInfo]]
    route_sources: dict[str, RouteSources] = field(default_factory=dict)
    """Routers declaring route sources."""
    route_sources_read: bool = False
    """False for a cache written before route sources existed: which of its
    routers declare some is unknown."""
    router_priorities: dict[str, RouterPriority] = field(default_factory=dict)
    """Routers declaring a priority."""
    router_priorities_read: bool = False
    """False for a cache written before router priorities existed: which of its
    routers declare one is unknown."""


class InitializableExtractor(ABC):
    @abstractmethod
    def reset(self, module_names: set[str] | None = None) -> None: ...

    @abstractmethod
    def init(self) -> None: ...


class AbstractRouteInfosExtractor(ABC):
    def __init__(
        self,
        defaults: ExtractorDefaultsProtocol,
        package_name: str,
        *,
        router_module_pattern: str = DEFAULT_ROUTER_MODULE_PATTERN,
    ) -> None:
        self.defaults = defaults
        self.package_name = package_name
        self.router_module_pattern = router_module_pattern

    @abstractmethod
    def preload_from_cache(self, cache: CachedExtractedRouteInfos) -> None: ...

    def scan_router_modules(self) -> Iterator[str]:
        spec = find_spec(self.package_name)
        if spec is None or not spec.origin:
            raise ValueError(f"Can't find file for module {self.package_name}")

        root_path = Path(spec.origin).parent

        yield from sorted(
            ".".join(
                [self.package_name, *path.relative_to(root_path).with_suffix("").parts]
            )
            for path in root_path.rglob(self.router_module_pattern)
        )

    def known_router_priority(self, module_name: str) -> int | None:
        """The priority of ``module_name`` when the extractor already knows it.

        ``None`` lets the loader read the declaration from the router's source.
        """
        return None

    @abstractmethod
    def extract_module_route_infos(
        self,
        module_name: str,
        router_variables: set[str] | None = None,
    ) -> list[ExtractedRouteInfo]: ...
