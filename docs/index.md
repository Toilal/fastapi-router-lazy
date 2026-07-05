FastAPI Router Lazy
===================

[![Latest Version](https://img.shields.io/pypi/v/fastapi-router-lazy.svg)](https://pypi.python.org/pypi/fastapi-router-lazy)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/Toilal/fastapi-router-lazy/blob/develop/LICENSE)
[![Build Status](https://img.shields.io/github/actions/workflow/status/Toilal/fastapi-router-lazy/ci.yml?branch=develop)](https://github.com/Toilal/fastapi-router-lazy/actions/workflows/ci.yml)
[![Codecov](https://img.shields.io/codecov/c/github/Toilal/fastapi-router-lazy)](https://codecov.io/gh/Toilal/fastapi-router-lazy)
[![semantic-release](https://img.shields.io/badge/%20%20%F0%9F%93%A6%F0%9F%9A%80-semantic--release-e10079.svg)](https://github.com/relekang/python-semantic-release)

**Lazy, on-demand loading of [FastAPI](https://fastapi.tiangolo.com/) routers.**

Large FastAPI applications pay for *every* router at startup: importing the
module, building each route's dependency graph and response model, generating
its OpenAPI schema. `fastapi-router-lazy` mounts a tiny *stub* per route and
loads the real router only on the first request matching one of its paths.

The full startup win — *unused router modules are never imported* — comes from
generating the route metadata ahead of time and shipping it, so the app reads
that cache at startup instead of importing every module. The default in-process
extractor is the simplest wiring, but it imports each module at startup to read
its routes: it mounts on demand without deferring the imports. See the
[extractors reference](./extractors.md) for which strategy defers imports.

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

Whether step 1 imports the modules depends on the extractor. The default
in-process extractor imports each module at startup to read its routes, so it
defers *mounting* but not the imports. Feed the extractor prebuilt metadata
(the checksum cache on a hit, or the Sandbox / variant-aware extractors) and
step 1 reads that metadata instead — then unused router modules are never
imported, and the first matching request pays the import cost once.

Quick start
-----------

Throughout, `"myapp"` is **your** importable Python package — the one the
extractor walks to find modules named `router.py`. Given a package laid out like

```text
myapp/                  # <- the package name you pass to route_infos_extractor
├── __init__.py
├── users/
│   └── router.py       # exposes `router = APIRouter()`
└── items/
    └── router.py
```

where each `router.py` exposes an `APIRouter`:

```python
# myapp/users/router.py
from fastapi import APIRouter

router = APIRouter()


@router.get("/users")
def list_users() -> list[str]:
    return ["alice", "bob"]
```

Lazy loading is two steps: generate the route metadata ahead of time, then run
the app against that metadata so no router module is imported until requested.

**1. Generate the route metadata** — at build time. This imports each module
once and writes `routes.json`:

```python
from pathlib import Path

from fastapi_router_lazy import route_infos_extractor

route_infos_extractor("myapp", cache=True, cache_file=Path("routes.json"))
```

**2. Run lazily** — at runtime. `strict=True` uses the prebuilt metadata and
never re-imports at startup, so unused router modules stay unimported until
their first matching request:

```python
from pathlib import Path

from fastapi import FastAPI

from fastapi_router_lazy import (
    RouterLoader,
    lazy_middleware_factory,
    route_infos_extractor,
)

app = FastAPI()

extractor = route_infos_extractor(
    "myapp", cache=True, cache_file=Path("routes.json"), strict=True
)
loader = RouterLoader(extractor, app)

middleware = lazy_middleware_factory(loader)
app.add_middleware(middleware)

# Register the stubs; real routers load on first matching request.
loader.load(middleware)
```

For a zero-config start, `route_infos_extractor("myapp")` (no cache) is the
simplest wiring, but it imports every module at startup to read its routes — it
mounts on demand without deferring imports. `route_infos_extractor` scans for
modules matching `router.py` by default; pass `router_module_pattern=` to change
it (e.g. `"routes.py"`, `"*_router.py"`).

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
