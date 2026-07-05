"""Checksum-based cache around another extractor (advanced, optional).

Extraction can be costly (it imports modules). This wrapper persists the
extracted route infos to a JSON file keyed by a per-module source checksum, so
subsequent starts reuse the cache and only re-extract modules whose source
changed. Generate the cache at build time and ship it; at runtime, set
``strict=True`` to fail fast instead of silently re-extracting.
"""

import dataclasses
import hashlib
import json
import logging
import os
from collections.abc import Iterator
from importlib.util import find_spec
from pathlib import Path
from typing import Any, ClassVar

from fastapi_router_lazy.extractors.abc import (
    AbstractRouteInfosExtractor,
    CachedExtractedRouteInfos,
    ExtractorDefaultsProtocol,
    InitializableExtractor,
)
from fastapi_router_lazy.route_info import ExtractedRouteInfo

DEFAULT_CACHE_FILENAME = "routes.json"

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


def dataclass_decoder(dct: dict[str, Any], cls: type) -> Any:
    if isinstance(dct, dict) and all(isinstance(v, list) for v in dct.values()):
        tuple_fields = _tuple_field_names(cls)
        return {
            k: [cls(**_coerce_tuples(item, tuple_fields)) for item in v]
            for k, v in dct.items()
        }
    return dct


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

    def get_invalid_modules(self) -> set[str]:
        router_modules = set(AbstractRouteInfosExtractor.scan_router_modules(self))

        cached = self.data.router_checksums

        invalid: set[str] = set()

        for name in cached:
            if name not in router_modules:
                invalid.add(name)

        for name in router_modules:
            if name not in cached:
                invalid.add(name)
                continue

            if module_checksum(name) != cached[name]:
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
        if isinstance(extractor, InitializableExtractor):
            extractor.reset(module_names)

        deleted_module_names: set[str] = set()

        if module_names is None:
            module_names = set(extractor.scan_router_modules())
        else:
            if data is None:
                data = cls.read_cache_file(cache_file)

            for module_name in module_names:
                try:
                    module_spec = find_spec(module_name)
                except ModuleNotFoundError:
                    module_spec = None
                if module_spec is None or module_spec.origin is None:
                    deleted_module_names.add(module_name)

        if data is None:
            data = CachedExtractedRouteInfos({}, {})

        module_names = module_names - deleted_module_names

        for module_name in module_names:
            route_infos = extractor.extract_module_route_infos(module_name)
            data.routes[module_name] = route_infos
            data.router_checksums[module_name] = module_checksum(module_name)

        for deleted in deleted_module_names:
            data.routes.pop(deleted, None)
            data.router_checksums.pop(deleted, None)

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
        with open(cache_file, "w") as fp:
            json.dump(data, fp, cls=DataclassEncoder, indent=2)
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

        with open(cache_file) as fp:
            data = json.load(
                fp, object_hook=lambda d: dataclass_decoder(d, ExtractedRouteInfo)
            )
        parsed = CachedExtractedRouteInfos(**data)
        cls._cache_file_cache[str(cache_file)] = (
            stat.st_mtime_ns,
            stat.st_size,
            parsed,
        )
        return parsed
