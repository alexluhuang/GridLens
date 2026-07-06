from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gridlens.core.project import Project
from gridlens.runner.gridpack_runner import GridpackRunRequest, run_gridpack_case


class FakeProcess:
    def __init__(self) -> None:
        self.stdout = iter(["GridPACK line 1\n", "GridPACK line 2\n"])

    def wait(self) -> int:
        return 0


class GridpackRunnerTests(unittest.TestCase):
    def _make_request(self, root: Path) -> tuple[GridpackRunRequest, Path]:
        xml = root / "input.xml"
        xml.write_text("<Configuration />", encoding="utf-8")

        project = Project("Pilot Project 3", root / "project")
        project_data = project.save([xml], "input.xml")
        run_dir = project.create_run_folder()

        request = GridpackRunRequest(
            project_data=project_data,
            run_dir=run_dir,
            image="pnnl/gridpack:latest",
            executable="ca.x",
            xml_filename="input.xml",
            mpi_processes=1,
            use_host_user=False,
            use_platform_flag=False,
        )
        return request, run_dir

    def test_terminal_output_is_teed_into_work_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            request, run_dir = self._make_request(Path(tmp))

            with patch("gridlens.runner.gridpack_runner.subprocess.Popen", return_value=FakeProcess()):
                result = run_gridpack_case(request)

            terminal_log = run_dir / "work" / "terminal.log"
            run_log = run_dir / "logs" / "run.log"

            self.assertEqual(result.terminal_log_file, terminal_log)
            self.assertTrue(terminal_log.exists())
            self.assertIn("GridPACK line 1", terminal_log.read_text(encoding="utf-8"))
            self.assertEqual(terminal_log.read_text(encoding="utf-8"), run_log.read_text(encoding="utf-8"))

            expected_sha = hashlib.sha256(b"<Configuration />").hexdigest()
            manifest = json.loads(result.manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["input_files"],
                [
                    {
                        "file_name": "input.xml",
                        "path_in_container": "/app/workspace/input.xml",
                        "size_bytes": len("<Configuration />"),
                        "sha256": expected_sha,
                    }
                ],
            )

    def test_docker_start_failure_is_written_to_status_and_logs(self) -> None:
        with TemporaryDirectory() as tmp:
            request, run_dir = self._make_request(Path(tmp))
            messages: list[str] = []

            with (
                patch(
                    "gridlens.runner.gridpack_runner.subprocess.Popen",
                    side_effect=OSError("docker unavailable"),
                ),
                self.assertRaises(OSError),
            ):
                run_gridpack_case(request, messages.append)

            status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            terminal_log = (run_dir / "work" / "terminal.log").read_text(encoding="utf-8")
            run_log = (run_dir / "logs" / "run.log").read_text(encoding="utf-8")

            self.assertEqual(status["status"], "failed")
            self.assertEqual(status["error"], "docker unavailable")
            self.assertIn("Docker run could not be started: docker unavailable", terminal_log)
            self.assertEqual(terminal_log, run_log)
            self.assertIn("Docker run could not be started", "".join(messages))


if __name__ == "__main__":
    unittest.main()
