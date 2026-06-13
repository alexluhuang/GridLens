from __future__ import annotations

from pathlib import Path
import unittest

from gridpack_workbench.runner.docker_command import build_gridpack_docker_command


class DockerCommandTests(unittest.TestCase):
    def test_command_contains_gridpack_docker_shape(self) -> None:
        command = build_gridpack_docker_command(
            work_dir=Path.cwd(),
            image="pnnl/gridpack:latest",
            executable="ca.x",
            xml_filename="input.xml",
            mpi_processes=4,
            network_mode="none",
            pull_policy="never",
            use_host_user=False,
            use_platform_flag=False,
        )

        self.assertEqual(command[:3], ["docker", "run", "--rm"])
        self.assertIn("--pull=never", command)
        self.assertIn("--network", command)
        self.assertIn("none", command)
        self.assertIn("-v", command)
        self.assertIn(f"{Path.cwd().resolve()}:/app/workspace", command)
        self.assertIn("-w", command)
        self.assertIn("/app/workspace", command)
        self.assertIn("pnnl/gridpack:latest", command)
        self.assertEqual(command[-5:], ["mpirun", "-n", "4", "ca.x", "input.xml"])

    def test_extra_args_are_split_without_shell(self) -> None:
        command = build_gridpack_docker_command(
            work_dir=Path.cwd(),
            image="example/gridpack:1.0",
            executable="powerflow.x",
            xml_filename="case.xml",
            mpi_processes=2,
            extra_docker_args="--cpus 4 --name gridpack-test",
            use_host_user=False,
            use_platform_flag=False,
        )

        self.assertIn("--cpus", command)
        self.assertIn("4", command)
        self.assertIn("--name", command)
        self.assertIn("gridpack-test", command)


if __name__ == "__main__":
    unittest.main()
