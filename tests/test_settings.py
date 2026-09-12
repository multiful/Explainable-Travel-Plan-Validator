"""설정 파일 경로와 환경변수 경계 테스트."""

from pathlib import Path

from src.data.models import Settings


def test_settings_env_file_is_project_absolute_path():
    env_file = Settings.model_config["env_file"]

    assert Path(env_file).is_absolute()
