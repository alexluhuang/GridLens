from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gridpack_workbench.core.project import Project, copy_project_inputs_to_run, open_project


class ProjectTests(unittest.TestCase):
    def test_project_save_and_open(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "case.raw"
            xml = root / "input.xml"
            raw.write_text("raw", encoding="utf-8")
            xml.write_text("<Configuration />", encoding="utf-8")

            project = Project("Pilot Project 1", root / "project")
            data = project.save([raw, xml], "input.xml")

            self.assertTrue(project.project_file.exists())
            self.assertEqual(data.xml_file_name, "input.xml")
            self.assertEqual(len(data.input_files), 2)

            opened_project, opened_data = open_project(project.project_file)
            self.assertEqual(opened_project.name, "Pilot Project 1")
            self.assertEqual(opened_data.name, "Pilot Project 1")

    def test_copy_project_inputs_to_run(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "case.raw"
            xml = root / "input.xml"
            raw.write_text("raw", encoding="utf-8")
            xml.write_text("<Configuration />", encoding="utf-8")

            project = Project("Pilot Project 2", root / "project")
            data = project.save([raw, xml], "input.xml")
            run_dir = project.create_run_folder()
            copied = copy_project_inputs_to_run(data, run_dir)

            self.assertEqual(len(copied), 2)
            self.assertTrue((run_dir / "work" / "case.raw").exists())
            self.assertTrue((run_dir / "work" / "input.xml").exists())


if __name__ == "__main__":
    unittest.main()
