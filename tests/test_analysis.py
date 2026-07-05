from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gridpack_workbench.analysis.distributions import generate_distribution_exports
from gridpack_workbench.analysis.dataset import build_run_analysis, gini, top_share
from gridpack_workbench.analysis.master import ensure_branch_master_exports
from gridpack_workbench.analysis.parsers import parse_input_xml, parse_success_file, summarize_success_file
from gridpack_workbench.analysis.summary import generate_run_report


class AnalysisTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("pandas"), "pandas is required for export generation")
    def test_success_summary_report_and_master_exports(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = _sample_run(Path(tmp))

            summary = summarize_success_file(run_dir)
            self.assertTrue(summary.exists)
            self.assertEqual(summary.success_count, 3)
            self.assertEqual(summary.failure_count, 1)

            report = generate_run_report(run_dir)
            self.assertTrue(Path(report["html_report"]).exists())
            self.assertTrue(Path(report["inventory_csv"]).exists())
            self.assertTrue(Path(report["chart_svg"]).exists())
            self.assertTrue(Path(report["analysis_manifest"]).exists())
            self.assertTrue(Path(report["master"]["master_csv"]).exists())
            self.assertTrue(Path(report["master"]["master_cleaned_csv"]).exists())
            self.assertTrue(Path(report["master"]["outliers_csv"]).exists())
            self.assertEqual(report["master"]["row_count"], 2)
            self.assertEqual(report["master"]["cleaned_row_count"], 1)
            self.assertEqual(report["master"]["outlier_row_count"], 1)

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
            self.assertEqual(manifest["tables"]["branch_metadata"]["row_count"], 2)
            self.assertTrue((run_dir / "reports" / "tables" / "perf_mm.csv").exists())

            perf_rows = dataset.tables["perf_mm"].rows
            pflow_mm_rows = dataset.tables["pflow_mm"].rows
            self.assertEqual(perf_rows[0]["voltage_class"], "230-344 kV")
            self.assertNotIn("max_utilization_pct", perf_rows[0])
            self.assertAlmostEqual(float(pflow_mm_rows[0]["max_utilization_pct"]), 100.0)

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

    def test_input_xml_parser_uses_manifest_xml_and_generic_network_configuration(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "2026-07-01_19-47-56"
            work_dir = run_dir / "work"
            work_dir.mkdir(parents=True)
            (run_dir / "manifest.json").write_text(
                json.dumps({"xml_file": "input_training_nottiny_nofilter_texas7k.xml"}),
                encoding="utf-8",
            )
            (work_dir / "input_training_nottiny_nofilter_texas7k.xml").write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<Configuration>
  <Contingency_analysis>
    <FullBranchN1>true</FullBranchN1>
    <minVoltage>0.9</minVoltage>
    <maxVoltage>1.1</maxVoltage>
  </Contingency_analysis>
  <Powerflow>
    <networkConfiguration>Texas7k_20210804.raw</networkConfiguration>
  </Powerflow>
</Configuration>
""",
                encoding="utf-8",
            )

            table = parse_input_xml(run_dir)

            self.assertEqual(table.source_file, "input_training_nottiny_nofilter_texas7k.xml")
            self.assertEqual(table.rows[0]["input_file"], "input_training_nottiny_nofilter_texas7k.xml")
            self.assertEqual(table.rows[0]["network_configuration"], "Texas7k_20210804.raw")
            self.assertTrue(table.rows[0]["full_branch_n1"])

    @unittest.skipUnless(
        importlib.util.find_spec("pandas") and importlib.util.find_spec("matplotlib"),
        "pandas and matplotlib are required for distribution generation",
    )
    def test_distribution_exports_are_written_to_run_exports(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = _sample_run(Path(tmp))
            ensure_branch_master_exports(run_dir)

            results = generate_distribution_exports(run_dir, ["area", "voltage_class"])
            self.assertEqual(len(results), 2)
            for result in results:
                self.assertTrue(result.table_csv.exists())
                self.assertTrue(result.graph_png.exists())
                self.assertIn(str(run_dir / "exports"), str(result.table_csv))
                self.assertEqual(result.code_path.name, "distributions.py")

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
0 / END OF LOAD DATA, BEGIN FIXED SHUNT DATA
0 / END OF FIXED SHUNT DATA, BEGIN GENERATOR DATA
0 / END OF GENERATOR DATA, BEGIN BRANCH DATA
 101, 102, '1 ', 0.010000, 0.050000, 0.000000, 100.00, 110.00, 120.00, 0.0, 0.0, 0.0, 0.0, 1, 1, 10.0, 1, 1.0
 102, 101, '1 ', 0.010000, 0.050000, 0.000000, 1.00, 1.00, 1.00, 0.0, 0.0, 0.0, 0.0, 1, 1, 10.0, 1, 1.0
0 / END OF BRANCH DATA, BEGIN TRANSFORMER DATA
0 / END OF TRANSFORMER DATA, BEGIN AREA DATA
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
    (work / "pflow.txt").write_text(
        "1 101 102 1 70 0 0\n"
        "2 102 101 1 3 0 0\n",
        encoding="utf-8",
    )
    (work / "pflow_mm.txt").write_text(
        "1 101 102 1 50 -60 120 -110 70 -100 100 1 2\n"
        "2 102 101 1 2 -5 20 -7 18 -1 1 3 4\n",
        encoding="utf-8",
    )
    (work / "qflow.txt").write_text(
        "1 101 102 1 10 0 0\n"
        "2 102 101 1 1 0 0\n",
        encoding="utf-8",
    )
    (work / "qflow_mm.txt").write_text(
        "1 101 102 1 10 -15 22 -25 12 -100 100 1 2\n"
        "2 102 101 1 1 -2 4 -3 3 -1 1 3 4\n",
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
