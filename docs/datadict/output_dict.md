# GridPACK output reference

This file summarizes GridPACK contingency-analysis inputs and output files that GridLens can generate, run, or parse.
GridPACK itself performs the power-flow and contingency calculations inside the Docker container. GridLens prepares XML
inputs, records run metadata, and parses the output files that appear in the run's `work/` directory.

## Configuration options

You configure GridPACK contingency analysis with XML input files. GridLens generates that XML from the Configuration tab
and stores it with the project's original inputs. Existing projects that already contain a saved XML configuration can
still be opened and run. Key options include:

### Contingency specification

You can specify contingencies in two ways (or combine both):

**Option 1: auto-generate N-1 contingencies**

```xml
<Contingency_analysis>
  <FullBranchN1>true</FullBranchN1>      <!-- N-1 for all branches -->
  <FullGeneratorN1>true</FullGeneratorN1> <!-- N-1 for all generators -->
</Contingency_analysis>
```

**Option 2: use a contingency list file**

```xml
<Contingency_analysis>
  <contingencyList>contingencies.xml</contingencyList>
</Contingency_analysis>
```

**Option 3: combine both** (auto-generate N-1 + custom N-K from file)

```xml
<Contingency_analysis>
  <FullBranchN1>true</FullBranchN1>
  <FullGeneratorN1>true</FullGeneratorN1>
  <contingencyList>custom_nk_contingencies.xml</contingencyList>
</Contingency_analysis>
```
When combined, GridPACK may skip duplicate contingency definitions from the file.

### Other options

The defaults below are the values GridLens uses when generating XML. Imported XML files can override them.

| Option | Description | Default |
|--------|-------------|---------|
| `groupSize` | Number of MPI processes per contingency (parallelization) | 1 |
| `printCalcFiles` | Write detailed output for each contingency | false |
| `minVoltage` | Minimum voltage threshold for violations (p.u.) | 0.9 |
| `maxVoltage` | Maximum voltage threshold for violations (p.u.) | 1.1 |
| `contingencyRating` | Branch rating set used for contingency loading checks | C |
| `qlim` | Enable reactive power limit enforcement (PV to PQ bus conversion) | true |
| `outputFormat` | Contingency-analysis output format | csv_flat |

### Contingency file format

GridLens does not currently ship a sample contingency-list XML file. Add a custom contingency-list file to the project
inputs when an imported or generated XML references one.

## Advanced features

The behaviors in this section are GridPACK/container calculation behaviors, not Python algorithms implemented by
GridLens. GridLens records and parses the resulting output when GridPACK writes it.

### Automatic slack bus transfer

When a generator contingency trips the slack bus generator, GridPACK may transfer the slack bus role to the largest
remaining online generator. This mimics commercial power flow tools (PSS/E, PowerWorld) behavior.

**Example output:**

```text
Slack bus transferred from bus 69 to bus 80 (capacity: 577.0 MW)
```

After the contingency analysis completes, the slack bus is restored to its original location.

### Slack capacity check

After the power flow solves, GridPACK may check if the slack bus generator output exceeds its Pmax rating. If the
required generation exceeds capacity, the contingency is marked as failed with a warning message:

```text
WARNING: Slack bus 80 generator output (475.3 MW) exceeds capacity (400.0 MW)
Insufficient generation capacity for contingency GN_69_1
```

A contingency that needs more generation than the available capacity is therefore flagged as a failure.

### Island detection

GridPACK may detect network islands (disconnected portions) caused by branch contingencies:

- A lone bus, meaning a bus with no active branches, is marked as isolated.
- An island, meaning a group of buses disconnected from the main network.

When isolation is detected, the isolated buses are excluded from the power flow solution, and a warning is added to the results. The main network portion is still solved if possible.

## Output files

The contingency analysis calculation produces a number of files summarizing the
results of the entire set of individual contingency simulations. Only results
for contingencies that ran to completion are included. Calculations that failed
either because of a numerical instability or because the calculations failed to
converge are not included in the results. The output files are described below.

### success.txt

This file summarizes the results of each contingency and
reports 1) whether the contingency calculation successfully ran to completion,
2) whether a violation was found (bus, branch, or both), and 3) whether any
buses were isolated.

Example output:

```text
contingency: 1 success: true violation: none
contingency: 2 success: true violation: branch
contingency: 3 success: true violation: none warning: isolated
contingency: 4 success: false
```

- `success: true` means the power flow converged and slack capacity is within limits.
- `success: false` means the power flow failed, an island was detected, or slack capacity was exceeded.
- `violation: none/bus/branch` reports whether voltage or thermal limits were violated.
- `warning: isolated` means one or more buses were isolated, as a lone bus or an island.

### vmag.txt

This file contains the average value of the voltage magnitude for
non-PV buses. It also contains the RMS fluctuations of the voltage magnitude
with respect to the voltage average and also with respect to the base case. The
columns are:

- Column 1: row index
- Column 2: bus ID
- Column 3: average voltage magnitude over all contingencies
- Column 4: RMS voltage magnitude fluctuations with respect to the average value
- Column 5: RMS voltage magnitude fluctuations with respect to the base case value

### vmag_mm.txt

This file contains the minimum and maximum values of the
voltage magnitude over all contingencies. It also contains the contingency index
for which the minimum or maximum value occurs.

- Column 1: row index
- Column 2: bus ID
- Column 3: base case value
- Column 4: minimum value over all contingencies
- Column 5: maximum value over all contingencies
- Column 6: deviation of minimum value from base case
- Column 7: deviation of maximum value from base case
- Column 8: contingency index of minimum value
- Column 9: contingency index of maximum value

### vang.txt

This file has the same structure as vmag.txt, except that the
stored values all represent the phase angle at each bus. PV buses are included
in this data.

### vang_mm.txt

This file has the same structure as vmag\_mm.txt, except that the
stored values all represent the phase angle at each bus. PV buses are included
in this data.

### pq_change_cnt.txt

This file is only created if the qlim flag is
set to true in the input file. It counts the number of times a PV bus is
changed to a PQ bus during the simulation.

- Column 1: row index
- Column 2: bus ID
- Column 3: number of contingencies where PV bus changed to PQ bus

### pgen.txt

This file contains the average value of the real power for each
generator in the system. It also contains the RMS deviations of the real power
fluctuations with respect to the average and also with respect to the base case.

- Column 1: row index
- Column 2: bus ID
- Column 3: 2 character generator ID
- Column 4: average value of real power for each generator
- Column 5: RMS fluctuation in the real power with respect to average value
- Column 6: RMS fluctuation in the real power with respect to base case value

### pgen_mm.txt

This file contains the minimum and maximum values of the real
power for each generator, as well as the contingency index for which those
values occured.

- Column 1: row index
- Column 2: bus ID
- Column 3: 2 character generator ID
- Column 4: real power generation for the base case
- Column 5: minimum value of real power generation
- Column 6: maximum value of real power generation
- Column 7: deviation of minimum value from base case
- Column 8: deviation of maximum value from base case
- Column 9: contingency index of minimum value
- Column 10: contingency index of maximum value

### qgen.txt

This file has the same structure as pgen.txt, except that the
stored values represent the reactive power at each generator.

### qgen_mm.txt

This file has the same structure as pgen\_mm.txt, except that
the stored values represent the reactive power at each generator.

### pflow.txt

This file contains the average value of the real power flow at
the "from" bus for each line element. It also contains the RMS fluctuations with
respect to the average value and the base case.

- Column 1: row index
- Column 2: bus ID for "from" bus
- Column 3: bus ID for "to" bus
- Column 4: 2 character line ID
- Column 5: average value of real power flow for "from" bus
- Column 6: RMS fluctuations of real power flow with respect to average value
- Column 7: RMS fluctuations of real power flow with respect to base case value

### pflow_mm.txt

This file contains the minimum and maximum values of the real
power flow at the "from" bus for each line element. It also contains the
contingency indices at which these values occur.

- Column 1: row index
- Column 2: bus ID for "from" bus
- Column 3: bus ID for "to" bus
- Column 4: 2 character line ID
- Column 5: base case value of real power flow
- Column 6: minimum value of real power flow
- Column 7: maximum value of real power flow
- Column 8: deviation of minimum value from the base case value
- Column 9: deviation of maximum value from the base case value
- Column 10: minimum allowable value of power flow (-rate A parameter)
- Column 11: maximum allowable value of power flow (rate A parameter)
- Column 12: contingency index of minimum value
- Column 13: contingency index of maximum value

### qflow.txt

This file has the same structure as pflow.txt except that all
values are for the reactive power flow at the "from" bus.

### qflow_mm.txt

This file has the same structure as pflow\_mm.txt except that
all values are for the reactive power flow at the "from" bus.

### perf_mm.txt

This file contains minimum and maximum values of the real
power flow performance index (this is the absolute value of the complex power on
each line divided by the line rating value, squared). It also contains the
contingency indices for which these values occur.

- Column 1: row index
- Column 2: bus ID for "from" bus
- Column 3: bus ID for "to" bus
- Column 4: 2 character line ID
- Column 5: base case value of the performance index
- Column 6: minimum value of the performance index
- Column 7: maximum value of the performance index
- Column 8: deviation of minimum value from the base case
- Column 9: deviation of maximum value from the base case
- Column 10: contingency index at which the minimum value occurs
- Column 11: contingency index at which the maximum value occurs

### perf_sum.txt

This file contains the sum of the performance index over all
lines for each contingency. It also contains the average value of the
performance index over all lines for each contingency.

- Column 1: contingency index (0 is the base case)
- Column 2: sum of performance index over all lines
- Column 3: average value of performance index over all lines

### line_flt_cnt.txt

This file contains the total number of faults found on
each line for all contingencies.

- Column 1: row index
- Column 2: bus ID for "from" bus
- Column 3: bus ID for "to" bus
- Column 4: 2 character line ID
- Column 5: total number of contingencies that result in a fault on this line
