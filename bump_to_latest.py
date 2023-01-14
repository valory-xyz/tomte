import requests
import subprocess
import toml

from copy import deepcopy
from pathlib import Path

LOWEST_SUPPORTED_PYTHON_VERSION = "3.7"

config_file_path = Path("pyproject.toml").open()
original_config = toml.load(config_file_path)
config_file_path.close()

# update versions
config = deepcopy(original_config)
deps = config["tool"]["poetry"]["dependencies"]

error = False
for key, value in deps.items():
    if key == "python":
        continue
    if key == "importlib-metadata":
        # just pinned for lower bound
        continue
    current_version = value["version"]

    # highest version for LOWEST_SUPPORTED_PYTHON_VERSION
    latest_version = current_version
    if key != "tox":
        with subprocess.Popen(["pip", "install", f"{key}", "--dry-run", "--python-version", f"{LOWEST_SUPPORTED_PYTHON_VERSION}", "--no-deps", "--target", "foo"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
            for line in process.stdout:
                line_txt = line.decode('utf8')
                target = f"Would install {key}-"
                if target in line_txt:
                    latest_version = line_txt.strip(target).strip("\n")
                    latest_version = f"=={latest_version}"
    else:
        # special case due to importlib-metadata clash
        latest_version = f"<4"

    print(f"Updating {key} to {latest_version}, from {current_version}")
    with subprocess.Popen(["poetry", "add", f"{key}@{latest_version}", "--optional"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
        for line in process.stdout:
            line_txt = line.decode('utf8')
            if "SolverProblemError" in line_txt:
                error = True
            print(line_txt)


