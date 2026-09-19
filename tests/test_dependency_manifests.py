"""배포용 requirements와 프로젝트 선언의 의존성 일치 검증."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _package_name(requirement: str) -> str:
    token = requirement.split(";", 1)[0].split("#", 1)[0].strip()
    token = token.split("[", 1)[0]
    return re.split(r"[<>=!~]", token, maxsplit=1)[0].strip().lower().replace("_", "-")


def test_runtime_dependency_manifests_are_in_sync() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = project["project"]["dependencies"]
    declared += project["project"]["optional-dependencies"]["dev"]
    pyproject_names = {_package_name(requirement) for requirement in declared}
    requirements_names = {
        _package_name(line)
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert requirements_names == pyproject_names
    assert {"scikit-learn", "ortools"} <= requirements_names
    assert "neo4j" not in requirements_names
