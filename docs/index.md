FastAPI Router Lazy
===================

**Lazy, on-demand loading of [FastAPI](https://fastapi.tiangolo.com/) routers.**

Large FastAPI applications pay for *every* router at startup: importing the
module, building each route's dependency graph and response model, generating
its OpenAPI schema. `fastapi-router-lazy` defers that work. It mounts a tiny
*stub* per route and only imports and mounts the real router the first time a
request matches one of its paths.

The core needs **nothing but FastAPI** and works with plain
`fastapi.APIRouter`. An optional extra adds variant/version-aware extraction on
top of [`fastapi-router-variants`](https://github.com/Toilal/fastapi-router-variants).

Install
-------

Install with [pip](https://pip.pypa.io/):

```bash
pip install fastapi-router-lazy
```

For variant/version-aware extraction, add the `variants` extra:

```bash
pip install "fastapi-router-lazy[variants]"
```

Or add it to your project with [uv](https://docs.astral.sh/uv/):

```bash
uv add fastapi-router-lazy
```

How it works
------------

1. An **extractor** enumerates, per router module, the routes it declares
   (`ExtractedRouteInfo`: path, HTTP methods or websocket, owning module and
   router variable, optional deployment/hidden flags).
2. The **middleware** registers a lightweight stub route for each of them.
3. On the first request matching a stub, the **loader** imports that one module,
   mounts the real router (and its parent chain), removes the consumed stubs,
   and the request falls through to the freshly-mounted route.

The first matching request pays the import cost once; every route stays
reachable, and unused routers are never imported.

Quick start
-----------

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

See the [usage guide](./usage.md) for eager loading, deployment filtering and
the request lifecycle, the [extractors reference](./extractors.md) for the
available extraction strategies, and the [API reference](./api.md) for every
public symbol.

Support
-------

This project is hosted on [GitHub](https://github.com/Toilal/fastapi-router-lazy).
Feel free to open an [issue](https://github.com/Toilal/fastapi-router-lazy/issues)
if you think you have found a bug or something is missing.

License
-------

FastAPI Router Lazy is licensed under the [MIT license](https://opensource.org/licenses/MIT).
