"""Shared fixtures for additional engineering parsers."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from engineering_data import Store
from common import load_config


@pytest.fixture
def data_store(tmp_path):
    s = Store(tmp_path / 'project.db')
    yield s
    s.db.close()


@pytest.fixture(scope='session')
def tk_root():
    """One Tk root for the whole test session: creating/destroying several roots in one process
    makes Tcl intermittently fail on this machine (tcl_findLibrary / missing ttk *.tcl)."""
    tk = pytest.importorskip('tkinter')
    root = tk.Tk()
    yield root
    root.destroy()


@pytest.fixture
def engineering_cfg():
    return load_config()
