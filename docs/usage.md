Usage
=====

`fastapi-router-lazy` is built from three cooperating pieces:

- an **extractor** (`AbstractRouteInfosExtractor`) that discovers router modules
  and enumerates the routes each declares, as serializable
  [`ExtractedRouteInfo`](./api.md#extractedrouteinfo) records;
- a **loader** (`RouterLoader`) that imports a module and mounts its real
  router(s) onto the application;
- a **middleware** (built by `lazy_middleware_factory`) that registers a stub
  route per declared route and, on the first matching request, drives the
  loader to mount the real router.

Throughout, `"myapp"` is **your** importable Python package — the one the
extractor walks to find modules named `router.py`, each exposing an `APIRouter`:

```text
myapp/                  # <- the package name you pass to route_infos_extractor
├── __init__.py
├── users/
│   └── router.py       # exposes `router = APIRouter()`
└── items/
    └── router.py
```

Lazy loading
------------

In lazy mode you register stubs at startup and let the middleware mount real
routers on demand. Pass the middleware class to `loader.load(...)` so it
registers a stub route for every declared route instead of mounting the routers
immediately:

```python
from fastapi import FastAPI

from fastapi_router_lazy import (
    RouterLoader,
    lazy_middleware_factory,
    route_infos_extractor,
)

app = FastAPI()

extractor = route_infos_extractor("myapp")
loader = RouterLoader(extractor, app)

middleware = lazy_middleware_factory(loader)
app.add_middleware(middleware)

# Register one stub per declared route.
loader.load(middleware)
```

`lazy_middleware_factory` returns a `LazyMiddleware` subclass bound to your
loader, ready to hand to `app.add_middleware`.

### Request lifecycle

On each incoming HTTP or websocket request, the middleware:

1. looks for a stub route that fully matches the request;
2. if one matches, tags the request scope with the
   `x-fastapi-router-lazy-loading-router` header (module + router variable),
   then calls `RouterLoader.load_router(module, variable)` to import the module
   and mount the real router;
3. removes the consumed stub routes so subsequent requests hit the real router
   directly;
4. lets the request fall through to the freshly-mounted route, and echoes the
   `x-fastapi-router-lazy-loading-router` header on the response so you can
   observe which module was loaded.

Each middleware built by `lazy_middleware_factory` gets its own `FastAPI` stub
app (`app_stub`), so separate applications keep independent stub tables.
Requests that are neither HTTP nor websocket pass straight through.

Eager loading
-------------

Without the middleware you can mount everything immediately — useful in tests or
when you don't want the first-request penalty. Call `loader.load()` with no
argument: it scans every router module and mounts each router right away,
returning the list of `LoadedRouter` objects mounted.

```python
from fastapi import FastAPI

from fastapi_router_lazy import RouterLoader, route_infos_extractor

app = FastAPI()
loader = RouterLoader(route_infos_extractor("myapp"), app)

loader.load()  # imports and mounts every scanned router now
```

You can also mount a specific subset:

```python
# One module (all its router variables):
loader.load_router("myapp.users.router")

# A specific router variable in a module:
loader.load_router("myapp.users.router", "router")

# Several modules or declarations at once:
loader.load_routers(["myapp.users.router", "myapp.items.router"])
loader.load_router_decls(["myapp.users.router", ("myapp.items.router", {"router"})])
```

Filtering by deployment
-----------------------

Routes can be tagged with a `deployment`, letting a single codebase be served by
several processes that each mount only their share. Pass `deployments=` to the
loader; only routes whose `deployment` is in that set (or `True`, meaning "every
deployment") are mounted. Routes without an explicit deployment fall back to the
extractor's `defaults.deployment`.

```python
from fastapi import FastAPI

from fastapi_router_lazy import RouterLoader, route_infos_extractor

app = FastAPI()
extractor = route_infos_extractor("myapp")

# Only routes tagged for the "api" deployment are mounted.
loader = RouterLoader(extractor, app, deployments={"api"})
```

Deployment tags are populated by the variant-aware extractor; see
[Extractors](./extractors.md).

Custom router module pattern
----------------------------

By default the extractor scans the package tree for files named `router.py`.
Override it with `router_module_pattern=`:

```python
extractor = route_infos_extractor("myapp", router_module_pattern="*_router.py")
```

The pattern is matched with `pathlib`'s `rglob` against each candidate file, so
globs such as `"routes.py"`, `"*_router.py"` or `"api/*.py"` all work.

Working with `fastapi-router-variants`
--------------------------------------

`VariantsRouterLoader` (from `fastapi_router_lazy.variants`, `variants` extra)
mounts `RouterWrapper` objects from
[`fastapi-router-variants`](https://github.com/Toilal/fastapi-router-variants),
including their `parent` chains: the routes are included through every parent
wrapper before reaching the application. It is a drop-in `RouterLoader`
subclass — use it in place of `RouterLoader` when your routers are wrappers. The
core package never imports `fastapi_router_variants`, so plain-FastAPI projects
pay nothing for the integration.
