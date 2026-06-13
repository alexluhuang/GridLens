from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gridpack_workbench.analysis.parsers import summarize_success_file
from gridpack_workbench.analysis.summary import generate_run_report


class AnalysisTests(unittest.TestCase):
    def test_success_summary_and_report(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "2026-06-12_12-00-00"
            work_dir = run_dir / "work"
            work_dir.mkdir(parents=True)
            (run_dir / "reports").mkdir()
            (work_dir / "success.txt").write_text("a true\nb false\nc true\n", encoding="utf-8")
            (work_dir / "pflow_mm.txt").write_text("demo output", encoding="utf-8")

            summary = summarize_success_file(run_dir)
            self.assertTrue(summary.exists)
            self.assertEqual(summary.success_count, 2)
            self.assertEqual(summary.failure_count, 1)

            report = generate_run_report(run_dir)
            self.assertTrue(Path(report["html_report"]).exists())
            self.assertTrue(Path(report["inventory_csv"]).exists())
            self.assertTrue(Path(report["chart_svg"]).exists())


if __name__ == "__main__":
    unittest.main()
