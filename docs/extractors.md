Extractors
==========

An **extractor** discovers the router modules of a package and enumerates, per
module, the routes each declares — as serializable
[`ExtractedRouteInfo`](./api.md#extractedrouteinfo) records. The loader and the
middleware consume those records to decide what to mount and where.

All extractors subclass `AbstractRouteInfosExtractor` and share:

- `scan_router_modules()` — walk the package tree and yield the dotted module
  names matching `router_module_pattern` (default `router.py`);
- `extract_module_route_infos(module_name, router_variables=None)` — return the
  routes a module declares, optionally restricted to specific router variables;
- `defaults` — an `ExtractorDefaultsProtocol` providing the fallback
  `deployment`.

The factory
-----------

`route_infos_extractor` is the convenience entry point. It builds a
`PlainRouteInfosExtractor` by default and can wrap it in a checksum cache:

```python
from pathlib import Path

from fastapi_router_lazy import route_infos_extractor

extractor = route_infos_extractor(
    "myapp",
    router_module_pattern="router.py",  # default
    cache=False,                        # wrap in a CachedRouteInfosExtractor
    cache_file=None,                    # defaults to ./routes.json when cache=True
    strict=False,                       # fail fast on a missing/stale cache
)
```

Pass `extractor=` to plug a different base extractor (for example a
variant-aware one), or `defaults=` to supply custom `ExtractorDefaults`.

Available extractors
--------------------

| Extractor | Extra | Defers imports? | Notes |
|-----------|-------|-----------------|-------|
| `PlainRouteInfosExtractor` | — | No | Default. Imports the module, reads `APIRouter.routes`. |
| `SandboxRouteInfosExtractor` | — | Yes (child process) | Isolates the imports in a subprocess. |
| `CachedRouteInfosExtractor` | — | Yes (on cache hit) | Persists extraction to a checksum-keyed JSON cache. |
| `RecordingRouteInfosExtractor` | `variants` | Yes | Variant/version-aware; extracts **without** importing route handlers. |

"Defers imports?" is whether the extractor lets the application start *without*
importing the router modules — the startup gain behind lazy loading. With the
default `Plain` extractor it does not: every scanned module is imported when
`loader.load(...)` enumerates its routes.

### Plain (default)

`PlainRouteInfosExtractor` needs nothing but FastAPI. It imports the target
module (running its handlers' import-time side effects), finds every `APIRouter`
exposed as a module attribute, and reads their already-built routes.

Because it imports each module to read its routes, `Plain` does **not** defer
imports: with the default extractor every router module is imported at startup,
when `loader.load(...)` runs. Its value is on-demand *mounting* (a small mounted
route table, deployment filtering), not a startup import saving. To also defer
the imports, feed the loader prebuilt metadata via a warm [cache](#cached), the
[Sandbox](#sandbox) extractor, or the [variant-aware](#variantversion-aware-variants)
one.

The module-level helper `extract_routes_from_module(module_name)` performs a
single-module extraction without any surrounding extractor.

### Sandbox

`SandboxRouteInfosExtractor` isolates module imports in a child process so their
(potentially heavy) import-time side effects never touch the parent interpreter.
The child imports each module, reads the routes off its FastAPI routers, and
pickles the results back. It propagates the parent's import path so the child
resolves the same modules, and needs nothing but FastAPI.

```python
from fastapi_router_lazy import (
    ExtractorDefaults,
    SandboxRouteInfosExtractor,
    RouterLoader,
)

extractor = SandboxRouteInfosExtractor(ExtractorDefaults(), "myapp")
loader = RouterLoader(extractor, app)
```

The module-level helper `extract_routes_sandboxed(modules, python_executable=...)`
runs the same extraction for a list of modules.

### Cached

Extraction imports modules, which can be costly. `CachedRouteInfosExtractor`
wraps any other extractor and persists the extracted route infos to a JSON file
keyed by a per-module source checksum, so subsequent starts reuse the cache and
only re-extract modules whose source changed.

```python
from pathlib import Path

from fastapi_router_lazy import route_infos_extractor

extractor = route_infos_extractor(
    "myapp", cache=True, cache_file=Path("routes.json")
)
```

Generate the cache at build time and ship it; at runtime set `strict=True` so a
missing or stale cache raises instead of silently re-extracting. The module-level
helper `module_checksum(module_name)` computes the checksum a cache entry is
keyed on.

### Variant/version-aware (`[variants]`)

With [`fastapi-router-variants`](https://github.com/Toilal/fastapi-router-variants),
a single router declaration expands into many route variants (API versions, path
prefixes, flavors). `RecordingRouteInfosExtractor` enumerates all of them
**without** importing the route handlers or building the routes: it imports the
module under `RouterWrapper.recording(...)`, where the route decorators become
no-ops that report each expanded variant with its full metadata (`version`,
`prefix`, `deployment`, `hidden`).

It lives in `fastapi_router_lazy.variants` and must be imported explicitly
(importing it requires the `variants` extra). Pair it with `VariantsRouterLoader`
from the same subpackage, which mounts `RouterWrapper` objects (including their
`parent` chains):

```python
from fastapi import FastAPI
from fastapi_router_variants import RouterWrapper

from fastapi_router_lazy.variants import (
    RecordingRouteInfosExtractor,
    VariantsRouterLoader,
)

app = FastAPI()

extractor = RecordingRouteInfosExtractor(RouterWrapper, "myapp")
loader = VariantsRouterLoader(extractor, app)
```

Writing your own extractor
--------------------------

Subclass `AbstractRouteInfosExtractor` and implement:

- `extract_module_route_infos(self, module_name, router_variables=None)` —
  return the list of `ExtractedRouteInfo` a module declares;
- `preload_from_cache(self, cache)` — populate the extractor from a
  `CachedExtractedRouteInfos` (raise `NotImplementedError` if you don't support
  caching).

`scan_router_modules()` is provided by the base class and works out of the box
from `package_name` and `router_module_pattern`; override it only if your
discovery differs.

If your extractor keeps in-memory state that a cache generator must be able to
invalidate, also implement `InitializableExtractor`:

- `init(self)` — extract every scanned module up front;
- `reset(self, module_names=None)` — drop cached state for the given modules
  (or all of them).

```python
from fastapi_router_lazy import (
    AbstractRouteInfosExtractor,
    CachedExtractedRouteInfos,
    ExtractedRouteInfo,
)


class MyExtractor(AbstractRouteInfosExtractor):
    def preload_from_cache(self, cache: CachedExtractedRouteInfos) -> None:
        raise NotImplementedError

    def extract_module_route_infos(
        self,
        module_name: str,
        router_variables: set[str] | None = None,
    ) -> list[ExtractedRouteInfo]:
        ...
```
