# fastapi-router-lazy

**Lazy, on-demand loading of [FastAPI](https://fastapi.tiangolo.com/) routers.**

Large FastAPI applications pay for *every* router at startup: importing the
module, building each route's dependency graph and response model, generating
its OpenAPI schema. `fastapi-router-lazy` defers that work. It mounts a tiny
stub per route and only imports and mounts the real router the first time a
request matches one of its paths. The first matching request pays the import
cost once; unused routers are never imported.

The core needs nothing but FastAPI and works with plain `fastapi.APIRouter`.

## Install

```bash
pip install fastapi-router-lazy
# variant/version-aware extraction:
pip install "fastapi-router-lazy[variants]"
```

## Usage

Given importable `router.py` modules that each expose an `APIRouter`, wire lazy
loading on the application:

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

Eager loading, deployment filtering, cached extraction, and the
variant/version-aware extractor (`[variants]`) are covered in the
documentation.

## Documentation

Full documentation is available at
[toilal.github.io/fastapi-router-lazy](https://toilal.github.io/fastapi-router-lazy/).
A preview of the in-development `develop` branch is published at
[toilal.github.io/fastapi-router-lazy/dev/](https://toilal.github.io/fastapi-router-lazy/dev/).

## Requirements

Python 3.12+ and FastAPI.

## License

MIT
