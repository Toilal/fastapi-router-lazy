"""Modules a router declares its cached route infos depend on.

A router computing its route infos from data declared in other modules lists
those modules in a module-level ``__route_sources__`` tuple of module names: the
cache checksums them along with the router. The declaration is read from the
router's source, without importing anything.
"""

import ast
import hashlib
from collections.abc import Sequence
from importlib.util import find_spec
from pathlib import Path

from fastapi_router_lazy.extractors.abc import RouteSources

ROUTE_SOURCES_VARIABLE = "__route_sources__"


def module_file(module_name: str) -> Path | None:
    """The source file of ``module_name``, found without importing anything.

    ``importlib.util.find_spec`` imports the parent packages of a dotted name;
    this walks the directories of the top-level package instead.
    """
    top, *parts = module_name.split(".")
    try:
        spec = find_spec(top)
    except (ImportError, ValueError):
        return None
    if spec is None:
        return None

    origin = Path(spec.origin) if spec.origin and spec.has_location else None
    locations = list(spec.submodule_search_locations or [])
    for part in parts:
        origin = None
        next_locations: list[str] = []
        for location in locations:
            directory = Path(location) / part
            if (directory / "__init__.py").is_file():
                origin = directory / "__init__.py"
                next_locations = [str(directory)]
                break
            if (Path(location) / f"{part}.py").is_file():
                origin = Path(location) / f"{part}.py"
                break
            if directory.is_dir():
                next_locations.append(str(directory))
        locations = next_locations
    if origin is None or origin.suffix != ".py":
        return None
    return origin


def router_checksum(module_name: str, sources: Sequence[str], own_checksum: str) -> str:
    """Checksum of a router and of the modules it declares as route sources.

    Without route sources, it is the router's own checksum, unchanged.
    """
    if not sources:
        return own_checksum
    digest = hashlib.sha256()
    digest.update(module_name.encode())
    digest.update(b"\0")
    digest.update(own_checksum.encode())
    for name in sorted(sources):
        digest.update(b"\0")
        digest.update(name.encode())
        digest.update(b"\0")
        path = module_file(name)
        digest.update(path.read_bytes() if path is not None else b"\0missing")
    return digest.hexdigest()


def read_route_sources(module_name: str) -> RouteSources | None:
    """The route sources ``module_name`` declares, ``None`` when it declares none.

    A declaration that is not a tuple or list of module names, or that names a
    module that cannot be found, gives a :class:`RouteSources` whose ``error``
    says so.
    """
    path = module_file(module_name)
    if path is None:
        return None
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except (SyntaxError, ValueError):
        return None

    values = [
        value
        for statement in tree.body
        for target, value in _assignments(statement)
        if target == ROUTE_SOURCES_VARIABLE
    ]
    if not values:
        return None
    names: list[str] = []
    for value in values:
        if not isinstance(value, (ast.Tuple, ast.List)) or not all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts
        ):
            return RouteSources(
                (),
                f"{module_name}: {ROUTE_SOURCES_VARIABLE} must be a tuple or list "
                f"of module names",
            )
        names.extend(
            e.value
            for e in value.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        )

    missing = [name for name in names if module_file(name) is None]
    found = tuple(sorted({name for name in names if name not in missing}))
    if missing:
        return RouteSources(
            found,
            f"{module_name}: declared route sources not found: {', '.join(missing)}",
        )
    return RouteSources(found)


def _assignments(statement: ast.stmt) -> list[tuple[str, ast.expr]]:
    if isinstance(statement, ast.Assign):
        return [
            (target.id, statement.value)
            for target in statement.targets
            if isinstance(target, ast.Name)
        ]
    if (
        isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.value is not None
    ):
        return [(statement.target.id, statement.value)]
    return []
