API reference
=============

Every symbol below is exported from the top-level `fastapi_router_lazy` package
(`from fastapi_router_lazy import ...`), except `RecordingRouteInfosExtractor`,
which lives in `fastapi_router_lazy.extractors.variants` and requires the
`variants` extra.

Loader
------

### `RouterLoader`

```python
RouterLoader(
    extractor: AbstractRouteInfosExtractor,
    app: FastAPI | None = None,
    deployments: set[str] | None = None,
)
```

Mounts routers on demand, one module (and router variable) at a time. Works with
plain `fastapi.APIRouter` objects; when the `variants` extra is installed,
`RouterWrapper` objects are supported too, including their `parent` chains.

Key methods:

- `load(lazy_registry=None)` — with no argument, scan every router module and
  mount each router now, returning `list[LoadedRouter]`. Passed a
  `LazyRouteRegistry` (such as a `LazyMiddleware` subclass), register a stub per
  declared route instead and return `None`.
- `load_router(module_name, variables=None)` — import one module and mount the
  given router variable(s); with `variables=None`, mount every variable the
  extractor reports for that module. Returns `list[LoadedRouter]`.
- `load_routers(module_names)` — `load_router` over an iterable of modules.
- `load_router_decl(router_decl)` / `load_router_decls(router_decls)` — mount
  from declarations, each either a module name or a `(module_name, variables)`
  tuple.
- `filter_with_deployments(route_infos)` — keep only the routes whose
  `deployment` matches the loader's `deployments` set (or `True`).

### `LoadedRouter`

```python
@dataclass
class LoadedRouter:
    router: APIRouter
    routes: list[BaseRoute]
```

The result of mounting one router: the router that was included and the concrete
routes it added to the application.

### `RouterLoaderMeta`

```python
@dataclass(frozen=True)
class RouterLoaderMeta:
    module_name: str
    router_variable: str
```

Stamped onto a mounted router (`router._loader_meta`) to record where it came
from.

### `LazyRouteRegistry`

Abstract base for anything that can register lazy stub routes. Implement the
classmethod `register_lazy_routes(module_route_infos)`. `LazyMiddleware`
implements it.

Middleware
----------

### `lazy_middleware_factory`

```python
lazy_middleware_factory(router_loader: RouterLoader) -> type[LazyMiddleware]
```

Build a `LazyMiddleware` subclass bound to `router_loader`, ready to pass to
`app.add_middleware(...)`. On the first request matching a stub, the middleware
loads the real router, removes the consumed stubs, and lets the request fall
through. Also exported under its internal name `factory`.

### `LazyMiddleware`

Base ASGI middleware / `LazyRouteRegistry`. Holds the stub routes on a
class-level `app_stub: FastAPI`. Notable members:

- `register_lazy_routes(module_route_infos)` — add a stub route (HTTP or
  websocket) per `ExtractedRouteInfo`.
- `get_stub_matching_route(scope, match=Match.FULL)` — find the stub matching a
  request scope.
- `remove_stub_routes(route_name)` — drop the stubs for a loaded router; when the
  last stub is consumed, an optional `_on_all_stubs_consumed` callback fires.

### `LAZY_LOADING_ROUTER_HEADER`

```python
LAZY_LOADING_ROUTER_HEADER = "x-fastapi-router-lazy-loading-router"
```

The header (`module:variable`) the middleware adds to the request scope and
echoes on the response when it lazily mounts a router.

Route infos
-----------

### `RouteType`

```python
RouteType = Literal["http", "websocket"]
```

### `RouteInfo`

```python
@dataclass(frozen=True, kw_only=True)
class RouteInfo:
    path: str
    type: RouteType = "http"
    methods: tuple[str, ...] | None = None
```

Base description of a single route.

### `ExtractedRouteInfo`

```python
@dataclass(frozen=True, kw_only=True)
class ExtractedRouteInfo(RouteInfo):
    router_variable: str
    router_module: str
    version: Any = None
    prefix: Any = None
    deployment: str | bool | None = None
    hidden: bool = False
```

A route discovered by an extractor, carrying enough to mount it without importing
the router: its owning module and router variable, optional `version`/`prefix`
(kept opaque so the core stays independent of any versioning scheme), a
`deployment` tag, and a `hidden` flag (served but not published). `build_variant(path)`
returns a copy with a different path.

### `MetaRouteInfo`

```python
@dataclass(frozen=True, kw_only=True)
class MetaRouteInfo(RouteInfo):
    router_variable: str
    version: Any = None
    prefix: Any = None
    deployment: str | bool | None = None
```

Manually declared route metadata, for routes defined outside a router.

Extractors
----------

### `AbstractRouteInfosExtractor`

```python
AbstractRouteInfosExtractor(
    defaults: ExtractorDefaultsProtocol,
    package_name: str,
    *,
    router_module_pattern: str = "router.py",
)
```

Base class for all extractors. Provides `scan_router_modules()` (walk the
package, yield dotted module names matching the pattern); subclasses implement
`extract_module_route_infos(module_name, router_variables=None)` and
`preload_from_cache(cache)`.

### `route_infos_extractor`

```python
route_infos_extractor(
    package_name: str,
    *,
    defaults: ExtractorDefaultsProtocol | None = None,
    extractor: AbstractRouteInfosExtractor | None = None,
    cache: bool = False,
    cache_file: Path | None = None,
    router_module_pattern: str = "router.py",
    strict: bool = False,
) -> AbstractRouteInfosExtractor
```

Factory building an extractor for `package_name`. Defaults to
`PlainRouteInfosExtractor`; `cache=True` wraps it in a `CachedRouteInfosExtractor`
persisted to `cache_file` (defaults to `./routes.json`).

### `PlainRouteInfosExtractor`

Default in-process extractor. Imports each module and reads the routes off its
plain FastAPI routers. Implements `InitializableExtractor`.

### `extract_routes_from_module`

```python
extract_routes_from_module(module_name: str) -> list[ExtractedRouteInfo]
```

Import one module and read the routes of its FastAPI routers, standalone.

### `SandboxRouteInfosExtractor`

```python
SandboxRouteInfosExtractor(
    defaults: ExtractorDefaultsProtocol,
    package_name: str,
    *,
    router_module_pattern: str = "router.py",
    python_executable: str = sys.executable,
)
```

Extractor isolating module imports in a subprocess. Implements
`InitializableExtractor`.

### `extract_routes_sandboxed`

```python
extract_routes_sandboxed(
    modules: list[str], python_executable: str = sys.executable
) -> list[ExtractedRouteInfo]
```

Extract routes for a list of modules in an isolated child process.

### `CachedRouteInfosExtractor`

```python
CachedRouteInfosExtractor(
    defaults: ExtractorDefaultsProtocol,
    package_name: str,
    cache_file: Path,
    extractor: AbstractRouteInfosExtractor,
    *,
    strict: bool = False,
)
```

Wraps another extractor with a checksum-keyed JSON cache. Re-extracts only the
modules whose source changed; `strict=True` raises on a missing or stale cache
instead of re-extracting.

### `module_checksum`

```python
module_checksum(
    module_name: str, algo: str = "sha256", chunk_size: int = 8192
) -> str
```

Hash of a module's source file — the key a cache entry is stored under.

### `RecordingRouteInfosExtractor` (`variants` extra)

```python
from fastapi_router_lazy.extractors.variants import RecordingRouteInfosExtractor

RecordingRouteInfosExtractor(
    router_wrapper_class: type[RouterWrapper],
    package_name: str,
    *,
    router_module_pattern: str = "router.py",
    defaults: ExtractorDefaultsProtocol | None = None,
)
```

Variant/version-aware extractor. Imports modules under
`RouterWrapper.recording(...)` to enumerate every expanded variant with full
metadata, without importing route handlers or building the routes. Requires the
`variants` extra.

Supporting types
----------------

### `ExtractorDefaultsProtocol`

Structural protocol for the defaults an extractor relies on — currently a single
`deployment: str | None` attribute. `fastapi_router_variants.RouterDefaults`
satisfies it structurally.

### `ExtractorDefaults`

```python
@dataclass
class ExtractorDefaults:
    deployment: str | None = None
```

Concrete default `ExtractorDefaultsProtocol` implementation.

### `InitializableExtractor`

Mixin for extractors that keep invalidatable in-memory state: `init()` extracts
every scanned module up front, `reset(module_names=None)` drops cached state.

### `CachedExtractedRouteInfos`

```python
@dataclass
class CachedExtractedRouteInfos:
    router_checksums: dict[str, str]
    routes: dict[str, list[ExtractedRouteInfo]]
```

The on-disk cache payload: per-module source checksums and the extracted routes.

### `__version__`

The installed package version string.
