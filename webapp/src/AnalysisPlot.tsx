import { useEffect, useState } from "react";

type PlotComponent = (props: Record<string, unknown>) => JSX.Element;

export default function AnalysisPlot(props: Record<string, unknown>) {
  const [Plot, setPlot] = useState<PlotComponent | null>(null);

  useEffect(() => {
    let active = true;

    async function loadPlot() {
      const [{ default: createPlotlyComponent }, { default: Plotly }] = await Promise.all([
        import("react-plotly.js/factory"),
        import("plotly.js-basic-dist-min"),
      ]);
      if (!active) {
        return;
      }
      setPlot(() => createPlotlyComponent(Plotly) as PlotComponent);
    }

    void loadPlot();
    return () => {
      active = false;
    };
  }, []);

  if (!Plot) {
    return <div className="chart-loading">Loading chart renderer...</div>;
  }

  return <Plot {...props} />;
}
