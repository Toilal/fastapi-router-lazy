"""Variant/version-aware support (optional ``variants`` extra).

Built on ``fastapi-router-variants``. Importing this subpackage requires the
optional extra (``pip install fastapi-router-lazy[variants]``); the core
package never imports it.

``RecordingRouteInfosExtractor`` records the routes in the current process;
``SandboxRecordingRouteInfosExtractor`` records them in a child process, for
applications whose router modules have import-time side effects that cannot
run twice in one interpreter.
"""

from fastapi_router_lazy.variants.extractor import RecordingRouteInfosExtractor
from fastapi_router_lazy.variants.loader import VariantsRouterLoader
from fastapi_router_lazy.variants.sandbox import (
    SandboxRecordingRouteInfosExtractor,
    record_routes_sandboxed,
)

__all__ = [
    "RecordingRouteInfosExtractor",
    "SandboxRecordingRouteInfosExtractor",
    "VariantsRouterLoader",
    "record_routes_sandboxed",
]
