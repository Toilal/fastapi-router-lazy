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
2. if one matches, calls `RouterLoader.load_router(module, variable)` (both
   derived from the stub name) to import the module and mount the real router;
3. removes the consumed stub routes so subsequent requests hit the real router
   directly;
4. lets the request fall through to the freshly-mounted route, and echoes the
   `x-fastapi-router-lazy-loading-router` header on the response so you can
   observe which module was loaded. The header is set on the response only; it
   is never injected into the request the downstream handlers see.

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

Filtering is **per route**: `filter_with_deployments` decides mount-or-not for
each `ExtractedRouteInfo` individually, so a single router variable can have some
of its routes mounted and others skipped depending on their tags. The `hidden`
flag on a route (an internal-only route, served but not published) is metadata
for consumers — the loader does **not** consult it when deciding what to mount.

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

Route order
-----------

Router modules are mounted in decreasing priority order, then module name
order, then router variable order within a module, the way a hand-written list
of `include_router` calls sorted that way would mount them. A module declares
its priority with a module-level integer, `0` when it declares none:

```python
ROUTER_LAZY_PRIORITY = 10  # mounted before the modules without a priority
```

A negative priority mounts the module after the modules without one. The value
is read from the module's source without importing it, like
`__route_sources__`, and the route infos cache stores it: a value that is not
an integer literal is reported as an invalid declaration and counts as `0`.

A router mounted lazily is inserted at its position
among the routers already mounted, whatever the order of the requests that
loaded them, so a request that fully matches a route resolves to the same route
in lazy and eager mode, as long as every router is mounted by `load()` or by a
request. A router mounted from an explicit list keeps the place that list gives
it in both modes, so an application mixing explicit lists with the canonical
order can resolve a request differently in each mode.
Within a router, routes keep their declaration order. Routes declared directly
on the application are left where they are, and routers mounted from an explicit
list (`load_routers`, `load_router_decls`) keep the order of that list.

For the same route to win in lazy and eager mode, declare routes directly on
the application before calling `load()` in either mode. If a direct route is
declared after `load()`, it can take precedence over a matching router route
in lazy mode while following that router route in eager mode. A router loaded
lazily is placed among the routers already loaded, regardless of routes declared
on the application in between: a route declared after a lazy load can be
shadowed by a router loaded later that matches the same request.

When two routes from different modules are mounted in canonical order and both
fully match the request, such as `/items/{item_id}` and `/items/special` for
`/items/special`, the route from the module with the higher priority takes
precedence over the other, then, at equal priority, the route from the module
whose name sorts first.

Limitations
-----------

Lazy loading trades a little runtime dynamism for startup speed. Keep these in
mind:

- **The schema is incomplete until routes are hit.** A lazily-declared route is
  absent from `/openapi.json` and `/docs` until its first matching request
  mounts the real router. If you need a complete schema up front (contract
  tests, generated clients), mount eagerly (`loader.load()` with no argument) or
  pre-warm the routes you care about.
- **No `include_router`-level `prefix`.** Routers are included as-is by the
  loader; there is no `prefix=` applied at mount time. Bake any prefix into the
  router itself (`APIRouter(prefix=...)`).
- **Stub match order.** A stub and a real route can share a path; Starlette
  resolves the ambiguity by match order. Routers follow the
  [route order](#route-order) whatever the order of the requests that load
  them.
- **Concurrency at first request.** Mounting happens on the first matching
  request. If several requests for the same not-yet-mounted route arrive
  concurrently, they may each drive a mount; the loader is not designed for
  concurrent first-touch mounting of the same router.
