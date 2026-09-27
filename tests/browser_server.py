"""Explicit browser-test app factory. Not a production provider or mode."""
import os
from types import SimpleNamespace
from insurelens.server import create_app
from tests.nim_fixture import ScriptedNim


def create_test_app():
    return create_app(root=os.environ["DATA_DIR"], nim=ScriptedNim(), drugs=SimpleNamespace(enabled=False))
