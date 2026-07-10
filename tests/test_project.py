from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gridlens.core.project import Project, copy_project_inputs_to_run, open_project
from gridlens.core.validation import ValidationError


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

    def test_project_save_allows_configuration_generated_later(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "case.raw"
            raw.write_text("raw", encoding="utf-8")

            project = Project("Raw Only Project", root / "project")
            data = project.save([raw], "")

            self.assertEqual(data.xml_file_name, "")
            self.assertEqual(len(data.input_files), 1)
            self.assertTrue((project.original_inputs_dir / "case.raw").exists())

    def test_save_generated_xml_adds_and_selects_project_input(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "case.raw"
            raw.write_text("raw", encoding="utf-8")

            project = Project("Generated XML Project", root / "project")
            data = project.save([raw], "")
            updated = project.save_generated_xml(data, "input.xml", "<Configuration />")

            self.assertEqual(updated.xml_file_name, "input.xml")
            self.assertEqual([record.file_name for record in updated.input_files], ["case.raw", "input.xml"])
            self.assertTrue((project.original_inputs_dir / "input.xml").exists())

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

    def test_project_root_cannot_be_nested_inside_managed_project_folders(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            xml = root / "input.xml"
            xml.write_text("<Configuration />", encoding="utf-8")

            project = Project("Pilot Project 3", root / "project")
            project.save([xml], "input.xml")
            run_dir = project.create_run_folder()

            with self.assertRaises(ValidationError):
                Project("Nested Runs Project", project.runs_dir)

            with self.assertRaises(ValidationError):
                Project("Nested Work Project", run_dir / "work")

    def test_project_save_requires_xml_file_to_be_an_input_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "case.raw"
            raw.write_text("raw", encoding="utf-8")

            project = Project("Missing XML Project", root / "project")

            with self.assertRaisesRegex(ValidationError, "selected XML file"):
                project.save([raw], "input.xml")

    def test_project_save_rejects_duplicate_input_file_names(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            first_xml = first / "input.xml"
            second_xml = second / "input.xml"
            first_xml.write_text("<Configuration />", encoding="utf-8")
            second_xml.write_text("<Configuration />", encoding="utf-8")

            project = Project("Duplicate Inputs Project", root / "project")

            with self.assertRaisesRegex(ValidationError, "unique file names"):
                project.save([first_xml, second_xml], "input.xml")


if __name__ == "__main__":
    unittest.main()
