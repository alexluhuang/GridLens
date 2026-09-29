# Analysis notes

The Branch Analysis and Transformer Analysis tabs use the same parsing, enrichment, and plotting pipeline. The
difference is the facility type filter: Branch Analysis includes non-transformer RAW branches, while
Transformer Analysis includes transformer-derived rows.

## Files read from a run

When Generate Graphs is clicked, GridLens reads the selected run directory. It first tries fresh cached
analysis tables from `reports/analysis_manifest.json` or `reports/interactive_analysis_manifest.json`. If no
compatible cache exists, it parses files under `work/` and may write an interactive cache under
`reports/interactive_tables/`.

- `input.xml` is used to find the network configuration RAW file. If the XML does not identify one, GridLens
  falls back to `training.raw`.
- Legacy GridPACK text output is parsed from fixed schemas such as `pflow_mm.txt` and `pflow.txt`. The
  embedded branch and transformer graphs are based on `pflow_mm`, because the graphs show each facility's
  maximum observed N-1 loading.
- For `ca-scalability-v2` csv-flat output, GridLens detects the flat result CSV, normalizes column aliases,
  and creates logical `pflow`, `pflow_mm`, and csv-flat branch metadata tables from the CSV.
- The RAW file supplies bus names, base kV, control area IDs and names, branch ratings, and
  branch-vs-transformer classification.

## Parsing and normalization

Every facility is keyed by `from_bus`, `to_bus`, `line_id`, and `section`. Legacy text output has no section,
so GridLens uses a blank section. Csv-flat output keeps the section column when present. Bus IDs are coerced
to integers, circuit IDs are stripped of surrounding quotes and whitespace, and malformed rows that do not
match the expected schema are rejected with parser notes.

## Csv-flat aggregation

Csv-flat files are handled before graph rows are built so the rest of the pipeline can work from the same
`pflow_mm` shape used by legacy output. GridLens recognizes aliases for event index, contingency name, from
bus, to bus, circuit ID, section, and loading percent. It aggregates the full flat file by facility key and
records:

- the number of contingency rows seen for the facility;
- mean, minimum, maximum, and maximum absolute `loading_percent`;
- base-case loading when the row is identified as the base case;
- the event index and contingency label associated with the worst absolute loading;
- the overload count, using either a truthy violation flag or loading at or above 100%.

The resulting `pflow_mm.max_utilization_pct` is the maximum absolute `loading_percent`. For csv-flat data,
GridLens does not divide by RAW Rate C for the plotted utilization, because the source already reports percent
loading. The csv-flat parser keeps only a small raw-row preview in memory, but the facility summaries are
computed from the full file using RAPIDS/cuDF, Dask, or a Python streaming fallback.

## RAW metadata cleaning

The RAW parser extracts three metadata sets before plotting:

- bus metadata: bus ID, bus name, base kV, area, zone, owner, voltage magnitude, and angle;
- area metadata: area ID and area name, used for readable control-area labels;
- branch-like metadata: non-transformer branch rows plus transformer-derived branch rows.

Non-transformer branches come from the RAW branch section and provide ratings such as `ratec`. Two-winding
transformer rows come from the transformer section. Three-winding transformers are represented as synthetic
terminal-to-internal branch rows only when GridPACK's observed output rows expose the internal transformer
bus. Transformer metadata includes terminal count, winding, transformer name, and internal bus when available.

After parsing, bus metadata is merged into branch-related tables. Each facility receives endpoint bus names,
endpoint base kV, endpoint area IDs and names, a combined control-area label, and a voltage class based on the
larger endpoint base kV. Csv-flat branch metadata is overlaid with matching RAW metadata where available;
unmatched csv-flat rows remain available as monitored facilities with their csv-flat keys and ratings.

## Facility filters

Both analysis tabs drop facilities before plotting unless they pass all of these checks:

- the facility has matching branch metadata for its key;
- the facility type is enabled for the current tab;
- the larger endpoint voltage is at least 50 kV;
- a finite utilization value can be computed.

Branch Analysis enables only `nontransformer_branch`. Transformer Analysis enables
`two_winding_transformer_branch`, `three_winding_transformer_branch`, and `transformer_equivalent_branch`, and
disables non-transformer branches. This is why the two tabs can produce different graphs from the same run.

## Utilization calculation

For legacy text output, GridLens computes each facility's maximum observed utilization from `pflow_mm` and the
RAW rating:

```text
max_utilization_pct = max(abs(min_value), abs(max_value)) / ratec * 100
```

`rate_c` is accepted as an equivalent rating column for csv-derived metadata, but legacy RAW ratings normally
come from `ratec`. Rows without a positive rating or without valid minimum/maximum real-power flow are
dropped. The contingency label shown in hover text is whichever side produced the larger absolute flow:
`min_contingency` if the minimum flow has the larger magnitude, otherwise `max_contingency`.

For csv-flat output, `pflow_mm.max_utilization_pct` is already populated from the source `loading_percent`, so
that direct value is used. The hover text reports the utilization source as either `pflow_mm` or
`csv_flat.loading_percent`.

## Grouping for the graphs

Each accepted facility becomes one plotted row with bus labels, endpoint voltages, control-area labels, the
worst contingency, the maximum utilization percent, and its source. The display label is
`from bus to to bus (line_id)`, using bus names when they were available from RAW.

Control-area grouping uses endpoint area names. If a facility connects two areas, its same maximum-utilization
value is counted once in each endpoint area bucket. If an area name is reused by multiple area IDs, GridLens
appends the area ID to make the label reproducible.

Voltage grouping for non-transformer branches uses the larger endpoint base kV: `50-99 kV`, `100-229 kV`,
`230-344 kV`, `345-499 kV`, or `500+ kV`. Transformer Analysis replaces voltage buckets with step-direction
buckets: step-up if the to-bus kV is higher than the from-bus kV, step-down if it is lower, same-voltage if
the endpoints differ by no more than 0.5 kV, and unknown if endpoint voltage is missing.

## What each chart shows

- **Mean Max Utilization by Control Area**: each bar is the arithmetic mean of `max_utilization_pct` for
  accepted facilities in that control area. The chart also tracks facility count and the min-to-max range used
  in hover text. The dashed 30% line is a visual reference, not a filtering rule.
- **Mean Max Utilization by Voltage Group or Step Direction**: each bar is the arithmetic mean of
  `max_utilization_pct` for the currently visible area selection, grouped by voltage bucket or transformer
  step direction.
- **Maximum Observed Branch/Transformer Utilization**: the curve plots one point per accepted facility after
  the current area and voltage/step filters. The default order is lowest to highest utilization. The green
  band from 0% to 100% marks nominal capability, and the 100% line marks the loading limit reference.

Clicking a control-area bar filters the other two charts to that area selection. Clicking a voltage-group or
step-direction bar filters the maximum-utilization curve. Sorting changes only the display order; it does not
change the underlying values.

## Reproducing the graphs from raw outputs

1. Start from the selected run's `work/` directory.
2. Read the XML to identify the RAW network file, or use `training.raw` if no XML network configuration is
   available.
3. Parse `pflow_mm.txt` using the columns documented above, or aggregate csv-flat `loading_percent` by
   `from_bus`, `to_bus`, `line_id`, and `section`.
4. Parse RAW bus, area, branch, and transformer metadata. Normalize bus IDs and circuit IDs the same way as
   the output tables.
5. Join `pflow_mm` to branch metadata on the facility key, then join endpoint bus and area metadata.
6. Apply the tab-specific facility type filter, require endpoint voltage >= 50 kV, and drop rows without a
   finite utilization value.
7. For legacy output, compute maximum utilization with `max(abs(min_value), abs(max_value)) / ratec * 100`.
   For csv-flat output, use the aggregated maximum absolute `loading_percent`.
8. Build the three summaries: mean of facility maxima by endpoint control area, mean of facility maxima by
   voltage bucket or transformer step direction, and the sorted list of facility maxima.

## Important non-inputs

The embedded Branch Analysis and Transformer Analysis graphs do not use `perf_mm.txt`, performance-index sums,
`qflow_mm.txt`, voltage violation tables, or `master_cleaned.csv`. The outlier removal used by the branch
master export and distribution-analysis workflow is not applied to these interactive graphs.
