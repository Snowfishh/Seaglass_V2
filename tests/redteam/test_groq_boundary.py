"""Offline-only checks for application/evaluation import and collection boundaries."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tomllib
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

pytestmark = pytest.mark.redteam
ROOT = Path(__file__).resolve().parents[2]


def test_default_collection_paths_exclude_the_eval_lane():
    options = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]
    assert options["testpaths"] == ["tests/unit", "tests/integration"]
    assert any(marker.split(":", 1)[0] == "redteam" for marker in options.get("markers", []))


@pytest.mark.parametrize("selection", [[], ["-m", "not redteam"]])
def test_app_only_collection_never_imports_eval_tests(selection, tmp_path):
    code = r'''
import importlib.abc
import json
import sys
from pathlib import Path

import pytest

root = Path.cwd()

class RejectEvalImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "eval" or fullname.startswith("eval."):
            raise AssertionError("application collection attempted an eval import")

class AppCollectionBoundary:
    def pytest_collectstart(self, collector):
        path = Path(collector.path)
        if root / "tests" / "redteam" in (path, *path.parents):
            raise AssertionError("application collection entered the eval test lane")
        if path.name == "test_redteam_playbook.py":
            raise AssertionError("application collection imported the eval playbook")

    def pytest_collection_finish(self, session):
        assert session.items, "application collection must not be empty"
        for item in session.items:
            path = Path(item.path)
            assert any(root / "tests" / lane in path.parents for lane in ("unit", "integration"))
            assert item.get_closest_marker("redteam") is None
        assert not any(name == "eval" or name.startswith("eval.") for name in sys.modules)
        print("APP_COLLECTION_COUNT=" + str(len(session.items)))

sys.meta_path.insert(0, RejectEvalImports())
raise SystemExit(pytest.main(json.loads(sys.argv[1]), plugins=[AppCollectionBoundary()]))
'''
    result = subprocess.run(
        [sys.executable, "-c", code, json.dumps(
            ["-q", "--collect-only", "--basetemp", str(tmp_path / "collection"), *selection])],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "APP_COLLECTION_COUNT=" in result.stdout
    assert "tests/redteam/" not in result.stdout
    assert "test_redteam_playbook.py" not in result.stdout


def test_production_import_graph_does_not_import_eval_or_read_campaign_config():
    code = r'''
import importlib
import importlib.abc
import sys
from pathlib import Path

campaign_root = Path.cwd() / "eval" / "redteam"

class RejectEvalImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "eval" or fullname.startswith("eval."):
            raise AssertionError("production attempted an eval import")

def reject_campaign_reads(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = Path(args[0].decode() if isinstance(args[0], bytes) else args[0]).resolve()
        if path == campaign_root or campaign_root in path.parents:
            raise AssertionError("production attempted a campaign read")

sys.meta_path.insert(0, RejectEvalImports())
sys.addaudithook(reject_campaign_reads)
for name in ("aspire_brain.config", "aspire_brain.providers", "aspire_brain.answers.service",
             "aspire_brain.main", "aspire_brain.cli"):
    importlib.import_module(name)
assert not any(name == "eval" or name.startswith("eval.") for name in sys.modules)
'''
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for path in (ROOT / "src" / "aspire_brain").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(name == "eval" or name.startswith("eval.") for name in names), path


def test_eval_namespace_resolves_from_repo_root_without_sys_path_edits():
    code = r'''
import sys
from pathlib import Path

before = tuple(sys.path)
from eval.redteam.groq import config
from eval.redteam.groq.config import OfflineContractConfig

assert Path(config.__file__).resolve() == Path.cwd() / "eval/redteam/groq/config.py"
assert OfflineContractConfig.__module__ == "eval.redteam.groq.config"
assert tuple(sys.path) == before
'''
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_eval_test_has_the_registered_redteam_marker(tmp_path):
    code = r'''
from pathlib import Path
import sys

import pytest

class EvalCollectionBoundary:
    def pytest_collection_finish(self, session):
        assert session.items, "explicit eval collection must not be empty"
        for item in session.items:
            assert item.get_closest_marker("redteam") is not None, item.nodeid
            assert Path.cwd() / "tests" / "redteam" in Path(item.path).parents
        print("EVAL_COLLECTION_COUNT=" + str(len(session.items)))

raise SystemExit(pytest.main(
    ["-q", "--collect-only", "--strict-markers", "--basetemp", sys.argv[1], "tests/redteam"],
    plugins=[EvalCollectionBoundary()],
))
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "eval-collection")],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "EVAL_COLLECTION_COUNT=" in result.stdout


def test_eval_config_is_frozen_offline_only_and_has_no_campaign_controls():
    from eval.redteam.groq.config import OfflineContractConfig

    config = OfflineContractConfig()
    assert config.contract_version == "v1"
    assert config.reasoning_effort == "low"
    assert config.live_enabled is False
    assert {field.name for field in fields(config)} == {
        "contract_version", "reasoning_effort", "live_enabled",
    }
    with pytest.raises(FrozenInstanceError):
        config.live_enabled = True


@pytest.mark.parametrize("overrides", [
    {"contract_version": "v2"},
    {"contract_version": ""},
    {"reasoning_effort": "high"},
    {"reasoning_effort": "unset"},
    {"live_enabled": True},
    {"live_enabled": 0},
    {"live_enabled": "false"},
])
def test_eval_config_rejects_unreviewed_or_live_variants(overrides):
    from eval.redteam.groq.config import OfflineContractConfig

    with pytest.raises(ValueError, match="Stage 5B"):
        OfflineContractConfig(**overrides)


def test_eval_config_has_no_environment_or_campaign_file_loader(monkeypatch):
    from eval.redteam.groq.config import OfflineContractConfig

    monkeypatch.setenv("ASPIRE_REDTEAM_LIVE_ENABLED", "true")
    monkeypatch.setenv("ASPIRE_REDTEAM_MAX_ROUNDS", "8")
    monkeypatch.setenv("ASPIRE_REDTEAM_CONFIG", "must-not-be-read.json")
    assert OfflineContractConfig().live_enabled is False
    with pytest.raises(TypeError):
        OfflineContractConfig(max_rounds=8)
