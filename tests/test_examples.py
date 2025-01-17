import os
import pytest
import subprocess

YAML_CONFIGS = [
    config.split(".")[0]
    for config in os.listdir("examples")
    if config.endswith(".yaml") and config != "base_config.yaml"
]


@pytest.mark.parametrize("yaml_config", YAML_CONFIGS)
def test_yaml_config(yaml_config):
    result = subprocess.run(
        [
            "optimum-benchmark",
            "--config-dir",
            "examples",
            "--config-name",
            yaml_config,
        ],
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8")
