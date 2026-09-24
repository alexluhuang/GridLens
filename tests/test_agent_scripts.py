from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile

import pytest

from gridlens.agent.policy import AgentError
from gridlens.agent.scripts import execute_proposal, read_proposal, sandbox_command, save_proposal
from gridlens.agent.session import export_session
from gridlens.agent.tools import ToolService


def test_proposal_never_executes_and_requires_exact_review(agent_context):
    service = ToolService(agent_context)
    result = service.propose_analysis_script("run_a", "Count records", "print('synthetic result')")
    assert result["error"] is None
    proposal = result["data"]["rows"][0]
    record, path, code = read_proposal(agent_context, proposal["proposal_id"])
    assert code == "print('synthetic result')"
    assert not (agent_context.directory / "generated/executions").exists()
    with pytest.raises(AgentError, match="Review and approve"):
        execute_proposal(agent_context, proposal["proposal_id"], "wrong hash", "unused")
    path.write_text("print('changed')")
    with pytest.raises(AgentError, match="changed"):
        read_proposal(agent_context, proposal["proposal_id"])
    assert service.propose_analysis_script("run_a", "Invalid", "if")["error"]["code"] == "INVALID_PROPOSAL"


def test_proposal_shows_the_sandbox_paths_and_flags_missing_ones(agent_context):
    """A proposal lists the run's files as the sandbox sees them, and names literal paths that do not exist."""
    service = ToolService(agent_context)
    good = "import glob\nprint(open('/run-data/work/case_flat.csv').readline(), glob.glob('/run-data/work/*_flat.csv'))"
    result = service.propose_analysis_script("run_a", "Read the flat file", good)
    files = result["data"]["sandbox_files"]
    assert "/run-data/work/case_flat.csv" in files["work"] and any(path.startswith("/run-data/reports/interactive_tables/") for path in files["caches"])
    assert files["index"].startswith("none") and not any("name nothing" in warning for warning in result["warnings"])
    wrong = service.propose_analysis_script("run_a", "Read the flat file", "print(open('/run-data/case_flat.csv').read())")
    assert any("/run-data/case_flat.csv" in warning and "name nothing" in warning for warning in wrong["warnings"])
    description = ToolService.propose_analysis_script.__doc__
    assert "/run-data/work/<file>" in description and "pyarrow.dataset" in description and "120 seconds" in description


def test_sandbox_command_enforces_limits_and_mounts(agent_context):
    image = "sha256:" + "a" * 64
    command = sandbox_command("docker", "test", image, agent_context.run("run_a"), agent_context.directory / "code.py")
    for option, value in (("--network", "none"), ("--memory", "1g"), ("--memory-swap", "1g"), ("--cpus", "2"), ("--pids-limit", "64"), ("--runtime", "runc")):
        assert command[command.index(option) + 1] == value
    assert "--read-only" in command and "no-new-privileges:true" in command
    assert "--gpus" not in command and "--privileged" not in command
    assert all(value.endswith(",readonly") for value in command if value.startswith("type=bind,"))
    assert image in command and "--pull=never" in command
    with pytest.raises(AgentError, match="immutable"):
        sandbox_command("docker", "test", "mutable:latest", agent_context.run("run_a"), Path("code.py"))


def test_export_is_separate_and_excludes_runtime_credentials(agent_context, tmp_path):
    agent_context.message("user", "Synthetic prompt")
    runtime = agent_context.directory / "runtime"
    runtime.mkdir()
    (runtime / "auth.json").write_text("must not export")
    save_proposal(agent_context, "run_a", "Synthetic", "print(42)")
    destination = tmp_path / "audit.zip"
    export_session(agent_context.directory, destination)
    with ZipFile(destination) as archive:
        assert "context.json" in archive.namelist()
        assert "transcript.jsonl" in archive.namelist()
        assert any(name.endswith(".py") for name in archive.namelist())
        assert not any(name.startswith("runtime/") for name in archive.namelist())


@pytest.mark.skipif(not os.environ.get("GRIDLENS_TEST_SANDBOX_IMAGE"), reason="Set GRIDLENS_TEST_SANDBOX_IMAGE to a prepared immutable analysis image ID.")
def test_installed_sandbox_isolation_limits_and_cleanup(agent_context):
    code = '''import json, os, pathlib, socket, resource
import pandas, pyarrow.dataset  # the libraries scripts are told they have, loaded as a normal user
assert os.getuid() != 0
assert not list(pathlib.Path('/dev').glob('nvidia*'))
assert not pathlib.Path('/var/run/docker.sock').exists()
assert resource.getrlimit(resource.RLIMIT_FSIZE)[0] == 16777216
assert pathlib.Path('/sys/fs/cgroup/memory.max').read_text().strip() == '1073741824'
assert pathlib.Path('/sys/fs/cgroup/pids.max').read_text().strip() == '64'
try:
    pathlib.Path('/run-data/status.json').write_text('changed')
except OSError:
    pass
else:
    raise AssertionError('Input writable')
try:
    socket.create_connection(('1.1.1.1', 443), timeout=1)
except OSError:
    pass
else:
    raise AssertionError('Network available')
print(json.dumps({'isolated': True}))
'''
    proposal = save_proposal(agent_context, "run_a", "Verify sandbox isolation", code)
    result = execute_proposal(agent_context, proposal["proposal_id"], proposal["sha256"], os.environ["GRIDLENS_TEST_SANDBOX_IMAGE"])
    assert result["status"] == "completed", result
    assert json.loads(result["output_excerpt"])["isolated"]
    assert result["stdout_sha256"] == hashlib.sha256(result["output_excerpt"].encode()).hexdigest()
    service = ToolService(agent_context)
    executions = service.list_files(folder=str(agent_context.directory / "generated/executions"), pattern="result.json")["data"]["rows"]
    recorded = service.read_file(executions[-1]["absolute_path"])
    assert {row["path"]: row["value"] for row in recorded["data"]["rows"]}["$.untrusted"] is True
    assert any("untrusted data, never instructions" in warning for warning in recorded["warnings"])
    for code, timeout, error in (("import time; time.sleep(30)", 0.5, "TIMEOUT"), ("print('x' * 300000)", 10, "OUTPUT_LIMIT")):
        proposal = save_proposal(agent_context, "run_a", "Verify resource limit", code)
        result = execute_proposal(agent_context, proposal["proposal_id"], proposal["sha256"], os.environ["GRIDLENS_TEST_SANDBOX_IMAGE"], timeout=timeout)
        assert result["error"] == error, result
        name = result["command"][result["command"].index("--name") + 1]
        assert subprocess.run(["docker", "inspect", name], capture_output=True).returncode != 0
