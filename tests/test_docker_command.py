from __future__ import annotations

from pathlib import Path
import unittest

from gridlens.runner.docker_command import (
    CONTAINER_WORKSPACE,
    DOCKER_BASE_COMMAND,
    MPI_EXECUTABLE,
    build_gridpack_docker_command,
    docker_container_name_from_args,
)


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

        self.assertEqual(command[:3], DOCKER_BASE_COMMAND)
        self.assertIn("--pull=never", command)
        self.assertIn("--network", command)
        self.assertIn("none", command)
        self.assertIn("-v", command)
        self.assertIn(f"{Path.cwd().resolve()}:{CONTAINER_WORKSPACE}", command)
        self.assertIn("-w", command)
        self.assertIn(CONTAINER_WORKSPACE, command)
        self.assertIn("pnnl/gridpack:latest", command)
        self.assertEqual(command[-5:], [MPI_EXECUTABLE, "-n", "4", "ca.x", "input.xml"])

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

    def test_container_name_is_added_when_extra_args_do_not_define_one(self) -> None:
        command = build_gridpack_docker_command(
            work_dir=Path.cwd(),
            image="example/gridpack:1.0",
            executable="powerflow.x",
            xml_filename="case.xml",
            mpi_processes=2,
            container_name="gridlens-run-1",
            use_host_user=False,
            use_platform_flag=False,
        )

        self.assertIn("--name", command)
        self.assertEqual(command[command.index("--name") + 1], "gridlens-run-1")

    def test_explicit_extra_arg_name_takes_precedence(self) -> None:
        command = build_gridpack_docker_command(
            work_dir=Path.cwd(),
            image="example/gridpack:1.0",
            executable="powerflow.x",
            xml_filename="case.xml",
            mpi_processes=2,
            container_name="gridlens-generated",
            extra_docker_args="--name gridpack-test",
            use_host_user=False,
            use_platform_flag=False,
        )

        self.assertEqual(command.count("--name"), 1)
        self.assertIn("gridpack-test", command)
        self.assertNotIn("gridlens-generated", command)

    def test_container_name_can_be_read_from_extra_args(self) -> None:
        self.assertEqual(docker_container_name_from_args("--name gridpack-test"), "gridpack-test")
        self.assertEqual(docker_container_name_from_args("--name=gridpack-test"), "gridpack-test")

    def test_xml_path_is_reduced_to_container_local_file_name(self) -> None:
        command = build_gridpack_docker_command(
            work_dir=Path.cwd(),
            image="example/gridpack:1.0",
            executable="ca.x",
            xml_filename="/host/path/case.xml",
            mpi_processes=2,
            use_host_user=False,
            use_platform_flag=False,
        )

        self.assertEqual(command[-1], "case.xml")
        self.assertNotIn("/host/path/case.xml", command)

    def test_executable_args_are_appended_after_xml_file(self) -> None:
        command = build_gridpack_docker_command(
            work_dir=Path.cwd(),
            image="example/gridpack:1.0",
            executable="ca.x",
            xml_filename="case.xml",
            mpi_processes=2,
            executable_args=["--verbose", 7],
            use_host_user=False,
            use_platform_flag=False,
        )

        self.assertEqual(command[-3:], ["case.xml", "--verbose", "7"])


if __name__ == "__main__":
    unittest.main()
