from __future__ import annotations

from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget


class NotesTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        browser = QTextBrowser()
        browser.setObjectName("documentPane")
        browser.setOpenExternalLinks(True)
        browser.setHtml(
            """
            <h1>Analysis Notes</h1>
            <p>The Branch Analysis and Transformer Analysis tabs use the same parsing, enrichment, and
            plotting pipeline. The difference is the facility type filter: Branch Analysis includes
            non-transformer RAW branches, while Transformer Analysis includes transformer-derived rows.</p>

            <h2>Files Read From a Run</h2>
            <p>When Generate Graphs is clicked, GridLens reads the selected run directory. It first tries
            fresh cached analysis tables from <code>reports/analysis_manifest.json</code> or
            <code>reports/interactive_analysis_manifest.json</code>. If no compatible cache exists, it
            parses files under <code>work/</code> and may write an interactive cache under
            <code>reports/interactive_tables/</code>.</p>
            <ul>
              <li><code>input.xml</code> is used to find the network configuration RAW file. If the XML
              does not identify one, GridLens falls back to <code>training.raw</code>.</li>
              <li>Legacy GridPACK text output is parsed from fixed schemas such as <code>pflow_mm.txt</code>
              and <code>pflow.txt</code>. The embedded branch and transformer graphs are based on
              <code>pflow_mm</code>, because the graphs show each facility's maximum observed N-1 loading.</li>
              <li>For <code>ca-scalability-v2</code> csv-flat output, GridLens detects the flat result CSV,
              normalizes column aliases, and creates logical <code>pflow</code>, <code>pflow_mm</code>, and
              csv-flat branch metadata tables from the CSV.</li>
              <li>The RAW file supplies bus names, base kV, control area IDs and names, branch ratings, and
              branch-vs-transformer classification.</li>
            </ul>

            <h2>Parsing and Normalization</h2>
            <p>Every facility is keyed by <code>from_bus</code>, <code>to_bus</code>,
            <code>line_id</code>, and <code>section</code>. Legacy text output has no section, so GridLens
            uses a blank section. Csv-flat output keeps the section column when present. Bus IDs are coerced
            to integers, circuit IDs are stripped of surrounding quotes and whitespace, and malformed rows
            that do not match the expected schema are rejected with parser notes.</p>

            <h2>Csv-Flat Aggregation</h2>
            <p>Csv-flat files are handled before graph rows are built so the rest of the pipeline can work
            from the same <code>pflow_mm</code> shape used by legacy output. GridLens recognizes aliases for
            event index, contingency name, from bus, to bus, circuit ID, section, and loading percent. It
            aggregates the full flat file by facility key and records:</p>
            <ul>
              <li>the number of contingency rows seen for the facility;</li>
              <li>mean, minimum, maximum, and maximum absolute <code>loading_percent</code>;</li>
              <li>base-case loading when the row is identified as the base case;</li>
              <li>the event index and contingency label associated with the worst absolute loading;</li>
              <li>the overload count, using either a truthy violation flag or loading at or above 100%.</li>
            </ul>
            <p>The resulting <code>pflow_mm.max_utilization_pct</code> is the maximum absolute
            <code>loading_percent</code>. For csv-flat data, GridLens does not divide by RAW Rate C for the
            plotted utilization, because the source already reports percent loading. The csv-flat parser keeps
            only a small raw-row preview in memory, but the facility summaries are computed from the full file
            using RAPIDS/cuDF, Dask, or a Python streaming fallback.</p>

            <h2>RAW Metadata Cleaning</h2>
            <p>The RAW parser extracts three metadata sets before plotting:</p>
            <ul>
              <li>bus metadata: bus ID, bus name, base kV, area, zone, owner, voltage magnitude, and angle;</li>
              <li>area metadata: area ID and area name, used for readable control-area labels;</li>
              <li>branch-like metadata: non-transformer branch rows plus transformer-derived branch rows.</li>
            </ul>
            <p>Non-transformer branches come from the RAW branch section and provide ratings such as
            <code>ratec</code>. Two-winding transformer rows come from the transformer section. Three-winding
            transformers are represented as synthetic terminal-to-internal branch rows only when GridPACK's
            observed output rows expose the internal transformer bus. Transformer metadata includes terminal
            count, winding, transformer name, and internal bus when available.</p>
            <p>After parsing, bus metadata is merged into branch-related tables. Each facility receives
            endpoint bus names, endpoint base kV, endpoint area IDs and names, a combined control-area label,
            and a voltage class based on the larger endpoint base kV. Csv-flat branch metadata is overlaid
            with matching RAW metadata where available; unmatched csv-flat rows remain available as monitored
            facilities with their csv-flat keys and ratings.</p>

            <h2>Facility Filters</h2>
            <p>Both analysis tabs drop facilities before plotting unless they pass all of these checks:</p>
            <ul>
              <li>the facility has matching branch metadata for its key;</li>
              <li>the facility type is enabled for the current tab;</li>
              <li>the larger endpoint voltage is at least 50 kV;</li>
              <li>a finite utilization value can be computed.</li>
            </ul>
            <p>Branch Analysis enables only <code>nontransformer_branch</code>. Transformer Analysis enables
            <code>two_winding_transformer_branch</code>, <code>three_winding_transformer_branch</code>, and
            <code>transformer_equivalent_branch</code>, and disables non-transformer branches. This is why the
            two tabs can produce different graphs from the same run.</p>

            <h2>Utilization Calculation</h2>
            <p>For legacy text output, GridLens computes each facility's maximum observed utilization from
            <code>pflow_mm</code> and the RAW rating:</p>
            <p><code>max_utilization_pct = max(abs(min_value), abs(max_value)) / ratec * 100</code></p>
            <p><code>rate_c</code> is accepted as an equivalent rating column for csv-derived metadata, but
            legacy RAW ratings normally come from <code>ratec</code>. Rows without a positive rating or without
            valid minimum/maximum real-power flow are dropped. The contingency label shown in hover text is
            whichever side produced the larger absolute flow: <code>min_contingency</code> if the minimum flow
            has the larger magnitude, otherwise <code>max_contingency</code>.</p>
            <p>For csv-flat output, <code>pflow_mm.max_utilization_pct</code> is already populated from the
            source <code>loading_percent</code>, so that direct value is used. The hover text reports the
            utilization source as either <code>pflow_mm</code> or <code>csv_flat.loading_percent</code>.</p>

            <h2>Grouping for the Graphs</h2>
            <p>Each accepted facility becomes one plotted row with bus labels, endpoint voltages, control-area
            labels, the worst contingency, the maximum utilization percent, and its source. The display label
            is <code>from bus to to bus (line_id)</code>, using bus names when they were available from RAW.</p>
            <p>Control-area grouping uses endpoint area names. If a facility connects two areas, its same
            maximum-utilization value is counted once in each endpoint area bucket. If an area name is reused
            by multiple area IDs, GridLens appends the area ID to make the label reproducible.</p>
            <p>Voltage grouping for non-transformer branches uses the larger endpoint base kV:
            <code>50-99 kV</code>, <code>100-229 kV</code>, <code>230-344 kV</code>,
            <code>345-499 kV</code>, or <code>500+ kV</code>. Transformer Analysis replaces voltage buckets
            with step-direction buckets: step-up if the to-bus kV is higher than the from-bus kV, step-down if
            it is lower, same-voltage if the endpoints differ by no more than 0.5 kV, and unknown if endpoint
            voltage is missing.</p>

            <h2>What Each Chart Shows</h2>
            <ul>
              <li><b>Mean Max Utilization by Control Area</b>: each bar is the arithmetic mean of
              <code>max_utilization_pct</code> for accepted facilities in that control area. The chart also
              tracks facility count and the min-to-max range used in hover text. The dashed 30% line is a
              visual reference, not a filtering rule.</li>
              <li><b>Mean Max Utilization by Voltage Group or Step Direction</b>: each bar is the arithmetic
              mean of <code>max_utilization_pct</code> for the currently visible area selection, grouped by
              voltage bucket or transformer step direction.</li>
              <li><b>Maximum Observed Branch/Transformer Utilization</b>: the curve plots one point per
              accepted facility after the current area and voltage/step filters. The default order is lowest
              to highest utilization. The green band from 0% to 100% marks nominal capability, and the 100%
              line marks the loading limit reference.</li>
            </ul>
            <p>Clicking a control-area bar filters the other two charts to that area selection. Clicking a
            voltage-group or step-direction bar filters the maximum-utilization curve. Sorting changes only the
            display order; it does not change the underlying values.</p>

            <h2>Reproducing the Graphs From Raw Outputs</h2>
            <ol>
              <li>Start from the selected run's <code>work/</code> directory.</li>
              <li>Read the XML to identify the RAW network file, or use <code>training.raw</code> if no XML
              network configuration is available.</li>
              <li>Parse <code>pflow_mm.txt</code> using the columns documented above, or aggregate csv-flat
              <code>loading_percent</code> by <code>from_bus</code>, <code>to_bus</code>,
              <code>line_id</code>, and <code>section</code>.</li>
              <li>Parse RAW bus, area, branch, and transformer metadata. Normalize bus IDs and circuit IDs the
              same way as the output tables.</li>
              <li>Join <code>pflow_mm</code> to branch metadata on the facility key, then join endpoint bus and
              area metadata.</li>
              <li>Apply the tab-specific facility type filter, require endpoint voltage &gt;= 50 kV, and drop
              rows without a finite utilization value.</li>
              <li>For legacy output, compute maximum utilization with
              <code>max(abs(min_value), abs(max_value)) / ratec * 100</code>. For csv-flat output, use the
              aggregated maximum absolute <code>loading_percent</code>.</li>
              <li>Build the three summaries: mean of facility maxima by endpoint control area, mean of facility
              maxima by voltage bucket or transformer step direction, and the sorted list of facility maxima.</li>
            </ol>

            <h2>Important Non-Inputs</h2>
            <p>The embedded Branch Analysis and Transformer Analysis graphs do not use <code>perf_mm.txt</code>,
            performance-index sums, <code>qflow_mm.txt</code>, voltage violation tables, or
            <code>master_cleaned.csv</code>. The outlier removal used by the branch master export and
            distribution-analysis workflow is not applied to these interactive graphs.</p>
            """
        )
        layout.addWidget(browser)
