# fastapi-router-lazy

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
its routes: it mounts on demand without deferring the imports. The documentation
covers which strategy defers imports.

The core needs nothing but FastAPI and works with plain `fastapi.APIRouter`.

## Install

```bash
pip install fastapi-router-lazy
# variant/version-aware extraction:
pip install "fastapi-router-lazy[variants]"
```

## Usage

The examples below use `"myapp"` as the name of **your** importable Python
package — the one the extractor walks to find modules named `router.py`, each
exposing an `APIRouter`:

```text
myapp/                  # <- the package name you pass to route_infos_extractor
├── __init__.py
├── users/
│   └── router.py       # exposes `router = APIRouter()`
└── items/
    └── router.py
```

Given that layout, lazy loading is two steps.

**1. Generate the route metadata** (at build time — imports each module once and
writes `routes.json`):

```python
from pathlib import Path

from fastapi_router_lazy import route_infos_extractor

route_infos_extractor("myapp", cache=True, cache_file=Path("routes.json"))
```

**2. Run lazily** (at runtime — reads the metadata and imports no router module
until its first matching request):

```python
from pathlib import Path

from fastapi import FastAPI

from fastapi_router_lazy import (
    RouterLoader,
    lazy_middleware_factory,
    route_infos_extractor,
)

app = FastAPI()

# strict=True: use the prebuilt metadata, never re-import at startup.
extractor = route_infos_extractor(
    "myapp", cache=True, cache_file=Path("routes.json"), strict=True
)
loader = RouterLoader(extractor, app)

middleware = lazy_middleware_factory(loader)
app.add_middleware(middleware)

# Register the stubs; real routers load on first matching request.
loader.load(middleware)
```

The default extractor (`route_infos_extractor("myapp")`, no cache) is the
simplest wiring, but it imports every module at startup to read its routes — it
mounts on demand without deferring imports. Eager loading, deployment filtering,
and the variant/version-aware extractor (`[variants]`) are covered in the
documentation.

## Limitations

Lazy loading trades some runtime dynamism for startup speed:

- lazily-declared routes are absent from `/openapi.json` and `/docs` until their
  first matching request mounts them (mount eagerly if you need a complete
  schema up front);
- no `prefix=` is applied at `include_router` time — bake prefixes into the
  `APIRouter` itself;
- a stub and a real route sharing a path are resolved by Starlette match order.

See the [Limitations](https://toilal.github.io/fastapi-router-lazy/usage/#limitations)
section of the docs for details.

## Documentation

Full documentation is available at
[toilal.github.io/fastapi-router-lazy](https://toilal.github.io/fastapi-router-lazy/).
A preview of the in-development `develop` branch is published at
[toilal.github.io/fastapi-router-lazy/dev/](https://toilal.github.io/fastapi-router-lazy/dev/).

## Requirements

Python 3.12+ and FastAPI.

## License

MIT
