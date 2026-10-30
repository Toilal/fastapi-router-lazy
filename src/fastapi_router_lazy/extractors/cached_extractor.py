"""Checksum-based cache around another extractor (advanced, optional).

Extraction can be costly (it imports modules). This wrapper persists the
extracted route infos to a JSON file keyed by a per-module source checksum, so
subsequent starts reuse the cache and only re-extract modules whose source
changed. Generate the cache at build time and ship it; at runtime, set
``strict=True`` to fail fast instead of silently re-extracting.

A router computing its route infos from other modules declares them in
``__route_sources__`` (see :mod:`~fastapi_router_lazy.extractors.route_sources`):
it is checksummed together with them.
"""

import dataclasses
import hashlib
import json
import logging
import os
import uuid
from collections.abc import Iterable, Iterator
from importlib.util import find_spec
from pathlib import Path
from typing import Any, ClassVar, TypeVar

from fastapi_router_lazy.extractors.abc import (
    AbstractRouteInfosExtractor,
    CachedExtractedRouteInfos,
    ExtractorDefaultsProtocol,
    InitializableExtractor,
    RouteSources,
)
from fastapi_router_lazy.extractors.route_sources import (
    ROUTE_SOURCES_VARIABLE,
    read_route_sources,
    router_checksum,
)
from fastapi_router_lazy.route_info import ExtractedRouteInfo

DEFAULT_CACHE_FILENAME = "routes.json"

_T = TypeVar("_T")

logger = logging.getLogger(__name__)


def module_checksum(
    module_name: str, algo: str = "sha256", chunk_size: int = 8192
) -> str:
    hasher = hashlib.new(algo)

    spec = find_spec(module_name)

    if spec is None or spec.origin is None:
        raise ValueError(f"Module file not found: {module_name}")

    with open(spec.origin, "rb") as fp:
        while chunk := fp.read(chunk_size):
            hasher.update(chunk)

    return hasher.hexdigest()


class DataclassEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return dataclasses.asdict(o)
        return super().default(o)


def _tuple_field_names(cls: type) -> set[str]:
    return {
        field.name for field in dataclasses.fields(cls) if "tuple" in str(field.type)
    }


def _coerce_tuples(item: dict[str, Any], tuple_fields: set[str]) -> dict[str, Any]:
    return {
        key: tuple(value) if key in tuple_fields and isinstance(value, list) else value
        for key, value in item.items()
    }


def _decode_dataclass(cls: type[_T], item: Any) -> _T:
    if not isinstance(item, dict):
        raise TypeError(f"Expected an object for {cls.__name__}, got {item!r}")
    return cls(**_coerce_tuples(item, _tuple_field_names(cls)))


def _decode_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"Expected an object, got {value!r}")
    return value


def decode_cached_route_infos(data: Any) -> CachedExtractedRouteInfos:
    data = _decode_mapping(data)
    return CachedExtractedRouteInfos(
        router_checksums=_decode_mapping(data["router_checksums"]),
        routes={
            module: [_decode_dataclass(ExtractedRouteInfo, item) for item in items]
            for module, items in _decode_mapping(data["routes"]).items()
        },
        route_sources={
            module: _decode_dataclass(RouteSources, item)
            for module, item in _decode_mapping(data.get("route_sources", {})).items()
        },
        route_sources_read=data.get("route_sources_read", False),
    )


def _warn_invalid_declaration(error: str) -> None:
    logger.warning(
        f"{error}: the router is re-extracted on every start outside strict mode "
        f"until {ROUTE_SOURCES_VARIABLE} is fixed."
    )


class CachedRouteInfosExtractor(AbstractRouteInfosExtractor):
    # Process-global memo of parsed cache files, keyed by path. Each entry
    # carries the (mtime_ns, size) the file had when read, so a file changed on
    # disk self-invalidates instead of serving a stale in-memory copy.
    _cache_file_cache: ClassVar[
        dict[str, tuple[int, int, CachedExtractedRouteInfos]]
    ] = {}

    def __init__(
        self,
        defaults: ExtractorDefaultsProtocol,
        package_name: str,
        cache_file: Path,
        extractor: AbstractRouteInfosExtractor,
        *,
        strict: bool = False,
    ) -> None:
        super().__init__(
            defaults,
            package_name,
            router_module_pattern=extractor.router_module_pattern,
        )
        self.cache_file = cache_file
        self.extractor = extractor
        self.strict = strict

        read_cached_data = self.read_cache_file(self.cache_file)
        self.extractor.preload_from_cache(read_cached_data)
        self.data = read_cached_data

        invalid_modules = self.get_invalid_modules()
        if not invalid_modules:
            logger.info("Using cached route infos.")
            if not self.strict and not self.data.route_sources_read:
                self.data = self.write_cache_file_from_extractor(
                    self.extractor, self.cache_file, set(), self.data
                )
            return

        if self.strict:
            raise ValueError(
                f"Invalid modules detected in route infos cache: {invalid_modules}. "
                f"The cache is expected to be generated ahead of time when running "
                f"in strict mode."
            )

        logger.info(
            f"Invalid modules detected: {invalid_modules}. "
            f"Updating route infos cache from extractor ..."
        )

        data = self.write_cache_file_from_extractor(
            self.extractor, self.cache_file, invalid_modules, read_cached_data
        )
        self.extractor.preload_from_cache(data)
        self.data = data

    def preload_from_cache(self, cache: CachedExtractedRouteInfos) -> None:
        raise NotImplementedError

    def route_sources(self) -> dict[str, RouteSources]:
        """The route sources of the cached routers, read from each router file
        only for a cache written before route sources existed."""
        if self.data.route_sources_read:
            return self.data.route_sources
        return {
            name: sources
            for name in self.data.router_checksums
            if (sources := read_route_sources(name)) is not None
        }

    def get_invalid_modules(self) -> set[str]:
        router_modules = set(AbstractRouteInfosExtractor.scan_router_modules(self))

        cached = self.data.router_checksums
        route_sources = self.route_sources()

        invalid: set[str] = set()

        for name in cached:
            if name not in router_modules:
                invalid.add(name)

        for name in router_modules:
            if name not in cached:
                invalid.add(name)
                continue

            sources = route_sources.get(name)
            modules = sources.modules if sources else ()
            if router_checksum(name, modules, module_checksum(name)) != cached[name]:
                invalid.add(name)
                continue

            # The cache shipped in strict mode is built from the same sources:
            # only a changed checksum can make it stale there. Outside strict
            # mode, the extraction that follows reports the declaration.
            if sources and sources.error:
                if self.strict:
                    _warn_invalid_declaration(sources.error)
                else:
                    invalid.add(name)

        return invalid

    def scan_router_modules(self) -> Iterator[str]:
        yield from self.data.routes.keys()

    def extract_module_route_infos(
        self,
        module_name: str,
        router_variables: set[str] | None = None,
    ) -> list[ExtractedRouteInfo]:
        module_route_infos = self.data.routes.get(module_name, [])
        if router_variables is None:
            return module_route_infos
        return [r for r in module_route_infos if r.router_variable in router_variables]

    @classmethod
    def write_cache_file_from_extractor(
        cls,
        extractor: AbstractRouteInfosExtractor,
        cache_file: Path,
        module_names: set[str] | None = None,
        data: CachedExtractedRouteInfos | None = None,
    ) -> CachedExtractedRouteInfos:
        """Extract ``module_names`` (default: every router module) into
        ``cache_file``, along with their route sources.

        For a cache written before route sources existed, every router declaring
        some is extracted too.
        """
        if module_names is not None:
            if data is None:
                data = cls.read_cache_file(cache_file)
            if not data.route_sources_read:
                module_names = module_names | {
                    name
                    for name in data.router_checksums
                    if read_route_sources(name) is not None
                }

        if isinstance(extractor, InitializableExtractor):
            extractor.reset(module_names)

        deleted_module_names: set[str] = set()

        if module_names is None:
            module_names = set(extractor.scan_router_modules())
        else:
            for module_name in module_names:
                try:
                    module_spec = find_spec(module_name)
                except ModuleNotFoundError:
                    module_spec = None
                # A router module is always a file: a name resolving to a package
                # is a router.py turned into router/router.py, whose entry would
                # otherwise stay invalid and be re-extracted on every start.
                if (
                    module_spec is None
                    or module_spec.origin is None
                    or module_spec.submodule_search_locations is not None
                ):
                    deleted_module_names.add(module_name)

        if data is None:
            data = CachedExtractedRouteInfos({}, {})

        module_names = module_names - deleted_module_names

        for module_name in module_names:
            route_infos = extractor.extract_module_route_infos(module_name)
            data.routes[module_name] = route_infos
            sources = read_route_sources(module_name)
            if sources is None:
                data.route_sources.pop(module_name, None)
            else:
                data.route_sources[module_name] = sources
                if sources.error:
                    _warn_invalid_declaration(sources.error)
            data.router_checksums[module_name] = router_checksum(
                module_name,
                sources.modules if sources else (),
                module_checksum(module_name),
            )

        for deleted in deleted_module_names:
            data.routes.pop(deleted, None)
            data.router_checksums.pop(deleted, None)
            data.route_sources.pop(deleted, None)

        data.route_sources_read = True
        cls.write_cache_file(data, cache_file)

        return data

    @classmethod
    def clear_file_cache(cls) -> None:
        """Drop the process-global in-memory memo of parsed cache files."""
        cls._cache_file_cache.clear()

    @classmethod
    def write_cache_file(
        cls, data: CachedExtractedRouteInfos, cache_file: Path
    ) -> None:
        # Several processes may regenerate the same file (pytest-xdist workers,
        # server workers on a first start): a temporary file of the same
        # directory swapped in by os.replace never exposes a truncated JSON.
        # Creating it with os.open rather than mkstemp keeps the umask-derived
        # mode an in-place write would give, instead of mkstemp's 0600.
        temporary_file = cache_file.with_name(
            f".{cache_file.name}.{uuid.uuid4().hex}.tmp"
        )
        fd = os.open(temporary_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        try:
            with os.fdopen(fd, "w") as fp:
                json.dump(data, fp, cls=DataclassEncoder, indent=2)
            os.replace(temporary_file, cache_file)
        except BaseException:
            temporary_file.unlink(missing_ok=True)
            raise
        stat = os.stat(cache_file)
        cls._cache_file_cache[str(cache_file)] = (stat.st_mtime_ns, stat.st_size, data)

    @classmethod
    def read_cache_file(cls, cache_file: Path) -> CachedExtractedRouteInfos:
        try:
            stat = os.stat(cache_file)
        except FileNotFoundError:
            return CachedExtractedRouteInfos({}, {})

        memo = cls._cache_file_cache.get(str(cache_file))
        if memo is not None and memo[0] == stat.st_mtime_ns and memo[1] == stat.st_size:
            return memo[2]

        try:
            with open(cache_file) as fp:
                parsed = decode_cached_route_infos(json.load(fp))
        except (ValueError, TypeError, KeyError) as exc:
            # A file left truncated by a killed writer, or shaped by an
            # incompatible version, must not fail every start: read as empty,
            # it is rebuilt, and strict mode still fails on the invalid modules.
            logger.warning(
                f"Unreadable route infos cache {cache_file}, ignoring it: {exc}"
            )
            return CachedExtractedRouteInfos({}, {})
        cls._cache_file_cache[str(cache_file)] = (
            stat.st_mtime_ns,
            stat.st_size,
            parsed,
        )
        return parsed


@dataclasses.dataclass(frozen=True)
class RouteInfosCacheMismatch:
    """Route infos of ``module`` on which the cache and a fresh extraction differ."""

    module: str
    missing: tuple[ExtractedRouteInfo, ...]
    """Extracted fresh, absent from the cache."""
    unexpected: tuple[ExtractedRouteInfo, ...]
    """In the cache, absent from a fresh extraction."""


def verify_route_infos_cache(
    extractor: CachedRouteInfosExtractor, module_names: Iterable[str] | None = None
) -> list[RouteInfosCacheMismatch]:
    """Compare a fresh extraction of ``module_names`` with the cache.

    ``module_names`` defaults to the routers declaring route sources. Run it in
    a test suite as a safety net against a missing or incomplete declaration
    (pass every router module to catch a router that declares nothing): an
    empty list means the cache is up to date for those modules.
    The wrapped extractor extracts them again, in this process unless it
    extracts in a subprocess itself.
    """
    names = sorted(extractor.route_sources() if module_names is None else module_names)
    inner = extractor.extractor
    if isinstance(inner, InitializableExtractor):
        inner.reset(set(names))

    mismatches: list[RouteInfosCacheMismatch] = []
    for name in names:
        fresh = inner.extract_module_route_infos(name)
        cached = extractor.extract_module_route_infos(name)
        missing = tuple(route for route in fresh if route not in cached)
        unexpected = tuple(route for route in cached if route not in fresh)
        if missing or unexpected:
            mismatches.append(RouteInfosCacheMismatch(name, missing, unexpected))
    return mismatches
