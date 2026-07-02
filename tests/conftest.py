"""Shared helpers to build throwaway importable router packages on disk."""

import shutil
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

MakePackage = Callable[[dict[str, str]], str]


@pytest.fixture
def make_package(tmp_path: Path) -> Iterator[MakePackage]:
    """Return a factory writing a package tree and making it importable.

    ``modules`` maps a dotted submodule path (relative to the package root,
    e.g. ``"users.router"``) to its source code. Intermediate packages get an
    empty ``__init__.py``. Returns the top-level package name.
    """
    created_packages: list[str] = []
    path_entry = str(tmp_path)
    sys.path.insert(0, path_entry)

    def _factory(modules: dict[str, str]) -> str:
        package = f"lazyapp_{uuid.uuid4().hex}"
        created_packages.append(package)
        root = tmp_path / package
        root.mkdir()
        (root / "__init__.py").write_text("")

        for dotted, source in modules.items():
            parts = dotted.split(".")
            directory = root
            for part in parts[:-1]:
                directory = directory / part
                directory.mkdir(exist_ok=True)
                init = directory / "__init__.py"
                if not init.exists():
                    init.write_text("")
            (directory / f"{parts[-1]}.py").write_text(source)

        return package

    try:
        yield _factory
    finally:
        if path_entry in sys.path:
            sys.path.remove(path_entry)
        for package in created_packages:
            for name in list(sys.modules):
                if name == package or name.startswith(f"{package}."):
                    del sys.modules[name]
            shutil.rmtree(tmp_path / package, ignore_errors=True)
