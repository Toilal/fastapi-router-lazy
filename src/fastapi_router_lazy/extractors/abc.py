import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Protocol

from fastapi_router_lazy.route_info import ExtractedRouteInfo

logger = logging.getLogger(__name__)

DEFAULT_ROUTER_MODULE_PATTERN = "router.py"


class ExtractorDefaultsProtocol(Protocol):
    """Minimal defaults an extractor relies on.

    ``fastapi_router_variants.RouterDefaults`` satisfies this structurally, so
    the variant-aware extractors can pass their router defaults directly.
    """

    deployment: str | None


@dataclass
class ExtractorDefaults:
    deployment: str | None = None


@dataclass
class CachedExtractedRouteInfos:
    router_checksums: dict[str, str]
    routes: dict[str, list[ExtractedRouteInfo]]


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

        for path in root_path.rglob(self.router_module_pattern):
            relative = path.relative_to(root_path)
            module_parts = [self.package_name, *relative.with_suffix("").parts]
            yield ".".join(module_parts)

    @abstractmethod
    def extract_module_route_infos(
        self,
        module_name: str,
        router_variables: set[str] | None = None,
    ) -> list[ExtractedRouteInfo]: ...
