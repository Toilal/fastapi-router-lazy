"""Variant/version-aware support (optional ``variants`` extra).

Built on ``fastapi-router-variants``. Importing this subpackage requires the
optional extra (``pip install fastapi-router-lazy[variants]``); the core
package never imports it.
"""

from fastapi_router_lazy.variants.extractor import RecordingRouteInfosExtractor
from fastapi_router_lazy.variants.loader import VariantsRouterLoader

__all__ = [
    "RecordingRouteInfosExtractor",
    "VariantsRouterLoader",
]
