import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


INSTALL = Path(__file__).resolve().parent
MODELS = ("router-sol", "router-astra", "opus", "fable",
          "router-luna", "haiku", "router-deepseek-flash")
JOB_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}")
HELLO = {
    "id": "hello", "instructions": "Reply briefly.", "request": "Say hello.",
    "expected": "A greeting.", "checks": [{"type": "contains", "text": "hello"}],
}


def command(job, root, spool):
    models = job.get("models", MODELS)
    if not isinstance(models, (list, tuple)) or not models or any(
        model not in MODELS for model in models
    ):
        raise ValueError("Choose one or more installed model presets")
    scenario = job.get("scenario", "hello")
    if scenario == "hello":
        source = INSTALL / "hello.json"
    else:
        if not isinstance(scenario, str) or not JOB_NAME.fullmatch(scenario):
            raise ValueError("Use a scenario filename stem from scenarios/")
        source = root / "scenarios" / f"{scenario}.json"
        if source.resolve() != source or not source.is_file():
            raise ValueError("Scenario must be a regular file inside scenarios/")
    args = [sys.executable, "-E", "-s", "-m", "evalharness", str(source),
            "--out", str(spool), "--config", str(INSTALL / "models.json")]
    for model in models:
        args.extend(["--model", model])
    if job.get("observe", False):
        args.append("--observe")
    return args


def process(job_file, root, spool):
    log_file = spool / f"{job_file.stem}.log"
    try:
        log = log_file.open("x", encoding="utf-8")
    except FileExistsError:
        return
    with log:
        try:
            if job_file.is_symlink() or not job_file.is_file() or job_file.stat().st_size > 8192:
                raise ValueError("Job must be a regular JSON file under 8 KiB")
            job = json.loads(job_file.read_text(encoding="utf-8"))
            args = command(job, root, spool)
            result = subprocess.run(
                args, cwd=INSTALL, stdout=log, stderr=subprocess.STDOUT, timeout=600,
            )
            print(f"exit_code={result.returncode}", file=log)
        except (ValueError, AttributeError, OSError, subprocess.TimeoutExpired) as error:
            print(f"Job error: {error}\nexit_code=2", file=log)


def main():
    root = Path((INSTALL / "workspace.txt").read_text(encoding="utf-8").strip()).resolve()
    spool = root / "results" / "live-jobs"
    if spool.resolve() != spool:
        raise ValueError("Job directory must be inside the workspace")
    (spool / "inbox").mkdir(parents=True, exist_ok=True)
    for key in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        if not os.environ.get(key):
            raise ValueError(f"{key} must be configured")
    (INSTALL / "hello.json").write_text(json.dumps(HELLO), encoding="utf-8")
    while True:
        for path in sorted((spool / "inbox").glob("*.json")):
            if JOB_NAME.fullmatch(path.stem):
                process(path, root, spool)
        time.sleep(2)


if __name__ == "__main__":
    main()
