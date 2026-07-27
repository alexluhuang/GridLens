/// <reference types="vite/client" />

declare module "react-plotly.js" {
  import { ComponentType } from "react";

  const Plot: ComponentType<Record<string, unknown>>;
  export default Plot;
}

declare module "react-plotly.js/factory" {
  import { ComponentType } from "react";

  export default function createPlotlyComponent(plotly: unknown): ComponentType<Record<string, unknown>>;
}

declare module "plotly.js-basic-dist-min";
