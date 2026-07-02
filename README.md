# fastapi-router-lazy

**Lazy, on-demand loading of [FastAPI](https://fastapi.tiangolo.com/) routers.**

Large FastAPI applications pay for *every* router at startup: importing the
module, building each route's dependency graph and response model, generating
its OpenAPI schema. `fastapi-router-lazy` defers that work. It mounts a tiny
*stub* per route and only imports and mounts the real router the first time a
request matches one of its paths.

The core needs **nothing but FastAPI** and works with plain
`fastapi.APIRouter`. An optional extra adds variant/version-aware extraction on
top of [`fastapi-router-variants`](https://github.com/Toilal/fastapi-router-variants).

## Install

```bash
pip install fastapi-router-lazy
# variant/version-aware extraction:
pip install "fastapi-router-lazy[variants]"
```

## How it works

1. An **extractor** enumerates, per router module, the routes it declares
   (`ExtractedRouteInfo`: path, HTTP methods or websocket, owning module and
   router variable, optional deployment/hidden flags).
2. The **middleware** registers a lightweight stub route for each of them.
3. On the first request matching a stub, the **loader** imports that one module,
   mounts the real router (and its parent chain), removes the consumed stubs,
   and the request falls through to the freshly-mounted route.

The first matching request pays the import cost once; every route stays
reachable, and unused routers are never imported.

## Quick start (plain FastAPI)

Given a project laid out as importable `router.py` modules, each exposing an
`APIRouter`:

```python
# myapp/users/router.py
from fastapi import APIRouter

router = APIRouter()


@router.get("/users")
def list_users() -> list[str]:
    return ["alice", "bob"]
```

Wire lazy loading on the application:

```python
from fastapi import FastAPI

from fastapi_router_lazy import (
    RouterLoader,
    lazy_middleware_factory,
    route_infos_extractor,
)

app = FastAPI()

# Default extractor: import each `router.py` and read its APIRouter routes.
extractor = route_infos_extractor("myapp")
loader = RouterLoader(extractor, app)

middleware = lazy_middleware_factory(loader)
app.add_middleware(middleware)

# Register the stubs; real routers load on first matching request.
loader.load(middleware)
```

`route_infos_extractor` scans for modules matching `router.py` by default; pass
`router_module_pattern=` to change it (e.g. `"routes.py"`, `"*_router.py"`).

### Eager loading

Without the middleware you can also mount everything immediately — useful in
tests or when you don't want the first-request penalty:

```python
from fastapi import FastAPI

from fastapi_router_lazy import RouterLoader, route_infos_extractor

app = FastAPI()
loader = RouterLoader(route_infos_extractor("myapp"), app)

loader.load()  # imports and mounts every scanned router now
```

### Filtering by deployment

Tag routes with a `deployment` and only mount the ones a given process serves:

```python
from fastapi import FastAPI

from fastapi_router_lazy import RouterLoader, route_infos_extractor

app = FastAPI()
extractor = route_infos_extractor("myapp")

# Only routes tagged for the "api" deployment are mounted.
loader = RouterLoader(extractor, app, deployments={"api"})
```

## Extractors

| Extractor | Extra | Notes |
|-----------|-------|-------|
| `PlainRouteInfosExtractor` | — | Default. Imports the module, reads `APIRouter.routes`. |
| `SandboxRouteInfosExtractor` | — | Isolates the imports in a subprocess. |
| `CachedRouteInfosExtractor` | — | Persists extraction to a checksum-keyed JSON cache. |
| `RecordingRouteInfosExtractor` | `variants` | Variant/version-aware; extracts **without** importing route handlers. |

### Cached extraction

Wrap any extractor in a checksum cache so subsequent starts reuse the result and
only re-extract modules whose source changed:

```python
from pathlib import Path

from fastapi_router_lazy import route_infos_extractor

extractor = route_infos_extractor(
    "myapp", cache=True, cache_file=Path("routes.json")
)
```

Generate the cache at build time and set `strict=True` at runtime to fail fast
if it is missing or stale.

### Variant/version-aware extraction (`[variants]`)

With `fastapi-router-variants`, routers expand a single declaration into many
route variants (API versions, path prefixes, flavors). The recording extractor
enumerates all of them **without** importing the route handlers or building the
routes — it imports the module under `RouterWrapper.recording(...)`:

```python
from fastapi import FastAPI
from fastapi_router_variants import RouterWrapper

from fastapi_router_lazy import RouterLoader
from fastapi_router_lazy.extractors.variants import RecordingRouteInfosExtractor

app = FastAPI()

extractor = RecordingRouteInfosExtractor(RouterWrapper, "myapp")
loader = RouterLoader(extractor, app)
```

## License

MIT
