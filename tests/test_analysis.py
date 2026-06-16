from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from gridpack_workbench.analysis.agent import AnalysisToolbox, NemoClawAgentService
from gridpack_workbench.analysis.dataset import build_run_analysis, gini, top_share
from gridpack_workbench.analysis.parsers import parse_success_file, summarize_success_file
from gridpack_workbench.analysis.summary import generate_run_report
from gridpack_workbench.core.app_settings import AppSettings


class AnalysisTests(unittest.TestCase):
    def test_success_summary_and_report_compatibility(self) -> None:
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
            self.assertTrue(Path(report["analysis_manifest"]).exists())

    def test_schema_parsers_metrics_manifest_and_raw_enrichment(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = _sample_run(Path(tmp))

            success = parse_success_file(run_dir)
            self.assertEqual(success.row_count, 4)
            self.assertEqual(success.rows[1]["violation"], "branch")
            self.assertTrue(success.rows[2]["isolated_warning"])

            dataset = build_run_analysis(run_dir)
            manifest = json.loads(dataset.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["tables"]["perf_mm"]["row_count"], 2)
            self.assertTrue((run_dir / "reports" / "tables" / "perf_mm.csv").exists())

            perf_rows = dataset.tables["perf_mm"].rows
            self.assertEqual(perf_rows[0]["voltage_class"], "230-344 kV")
            self.assertAlmostEqual(float(perf_rows[0]["max_utilization_pct"]), 120.0)

            thermal = dataset.metrics["thermal"]
            self.assertEqual(thermal["facility_count"], 2)
            self.assertEqual(thermal["facilities_over_100_pct"], 1)
            self.assertGreater(thermal["gini_worst_utilization"], 0)

            voltage = dataset.metrics["voltage"]
            self.assertEqual(voltage["low_voltage_violations"], 1)
            self.assertEqual(voltage["high_voltage_violations"], 1)

    def test_metric_helpers(self) -> None:
        self.assertAlmostEqual(gini([1, 1, 1]), 0.0)
        self.assertAlmostEqual(top_share([1, 1, 8], 1 / 3), 0.8)

    def test_agent_tools_citations_and_restricted_code(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = _sample_run(Path(tmp))
            toolbox = AnalysisToolbox(run_dir, max_rows=10, timeout_seconds=5)

            answer = NemoClawAgentService(AppSettings(nemoclaw_cli_path=sys.executable)).answer(
                run_dir,
                "What is the top thermal bottleneck?",
            )
            self.assertTrue(answer.supported)
            self.assertTrue(answer.citations)
            self.assertIn("perf_mm", answer.citations[1].source)

            result = toolbox.run_python_analysis(
                "rows = read_table('perf_mm', limit=1)\n"
                "print(rows[0]['row_index'])\n"
                "save_artifact('answer.txt', rows[0]['row_index'])\n"
            )
            self.assertTrue(result.data["ok"])
            self.assertTrue(Path(result.artifact_path).exists())

            with self.assertRaises(ValueError):
                toolbox.run_python_analysis("save_artifact('../bad.txt', 'nope')\n")

            unsupported = NemoClawAgentService(AppSettings(nemoclaw_cli_path=sys.executable)).answer(
                run_dir,
                "Tell me a market price forecast.",
            )
            self.assertFalse(unsupported.supported)
            self.assertTrue(unsupported.citations)


def _sample_run(root: Path) -> Path:
    run_dir = root / "runs" / "2026-06-12_12-00-00"
    work = run_dir / "work"
    (run_dir / "reports").mkdir(parents=True)
    work.mkdir(parents=True)
    (work / "success.txt").write_text(
        "\n".join(
            [
                "contingency: 1 success: true violation: none",
                "contingency: 2 success: true violation: branch",
                "contingency: 3 success: true violation: bus warning: isolated",
                "contingency: 4 success: false",
            ]
        ),
        encoding="utf-8",
    )
    (work / "input.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<Configuration>
  <Powerflow><networkConfiguration_v33>training.raw</networkConfiguration_v33></Powerflow>
  <Contingency_analysis>
    <FullBranchN1>true</FullBranchN1>
    <FullGeneratorN1>false</FullGeneratorN1>
    <groupSize>1</groupSize>
    <minVoltage>0.9</minVoltage>
    <maxVoltage>1.1</maxVoltage>
    <qlim>true</qlim>
    <outputFormat>text</outputFormat>
  </Contingency_analysis>
</Configuration>
""",
        encoding="utf-8",
    )
    (work / "training.raw").write_text(
        """0, 100.00, 33, 0, 0, 60.00
 101, 'BUS101', 138.0000, 1, 11, 1, 1, 1.0000, 0.0, 1.1000, 0.9000, 1.1000, 0.9000
 102, 'BUS102', 230.0000, 1, 12, 1, 1, 1.0000, 0.0, 1.1000, 0.9000, 1.1000, 0.9000
0 / END OF BUS DATA, BEGIN LOAD DATA
""",
        encoding="utf-8",
    )
    (work / "vmag_mm.txt").write_text(
        "1 101 1.00 0.88 1.05 -0.12 0.05 2 3\n"
        "2 102 1.00 0.95 1.12 -0.05 0.12 1 4\n",
        encoding="utf-8",
    )
    (work / "perf_mm.txt").write_text(
        "1 101 102 1 0.25 0.01 1.44 -0.24 1.19 1 2\n"
        "2 102 101 1 0.04 0.00 0.64 -0.04 0.60 3 4\n",
        encoding="utf-8",
    )
    (work / "perf_sum.txt").write_text(
        "0 0.29 0.145\n"
        "1 0.70 0.350\n"
        "2 2.08 1.040\n",
        encoding="utf-8",
    )
    (work / "line_flt_cnt.txt").write_text("1 101 102 1 3\n2 102 101 1 0\n", encoding="utf-8")
    (work / "pq_change_cnt.txt").write_text("1 101 2\n2 102 0\n", encoding="utf-8")
    (work / "pgen_mm.txt").write_text("1 101 G1 10 5 15 -5 5 1 2\n", encoding="utf-8")
    (work / "qgen_mm.txt").write_text("1 102 G1 3 1 8 -2 5 1 2\n", encoding="utf-8")
    return run_dir


if __name__ == "__main__":
    unittest.main()
