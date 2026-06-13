from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gridpack_workbench.core.project import Project
from gridpack_workbench.runner.gridpack_runner import GridpackRunRequest, run_gridpack_case


class FakeProcess:
    def __init__(self) -> None:
        self.stdout = iter(["GridPACK line 1\n", "GridPACK line 2\n"])

    def wait(self) -> int:
        return 0


class GridpackRunnerTests(unittest.TestCase):
    def test_terminal_output_is_teed_into_work_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
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

            with patch("gridpack_workbench.runner.gridpack_runner.subprocess.Popen", return_value=FakeProcess()):
                result = run_gridpack_case(request)

            terminal_log = run_dir / "work" / "terminal.log"
            run_log = run_dir / "logs" / "run.log"

            self.assertEqual(result.terminal_log_file, terminal_log)
            self.assertTrue(terminal_log.exists())
            self.assertIn("GridPACK line 1", terminal_log.read_text(encoding="utf-8"))
            self.assertEqual(terminal_log.read_text(encoding="utf-8"), run_log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
