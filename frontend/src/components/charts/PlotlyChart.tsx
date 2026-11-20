"use client";

import React, { useEffect, useRef } from "react";

export const CHART_COLORS = {
  navy: "#0F2942",
  cobalt: "#1E5B94",
  steel: "#64748B",
  steelLight: "#94A3B8",
  teal: "#0F766E",
  amber: "#B45309",
  crimson: "#B91C1C",
  grid: "#EEF1F5",
  axis: "#CBD5E1",
};

interface PlotlyChartProps {
  data: Record<string, unknown>[];
  layout?: Record<string, unknown>;
  height?: number;
  className?: string;
  onPointClick?: (point: Record<string, unknown>) => void;
}

export function PlotlyChart({ data, layout = {}, height = 310, className = "", onPointClick }: PlotlyChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const plotlyRef = useRef<any>(null);

  useEffect(() => {
    let active = true;
    const el = containerRef.current;
    if (!el) return;

    const mergedLayout: Record<string, unknown> = {
      autosize: true,
      height,
      margin: { t: 22, r: 18, b: 44, l: 56, ...(layout.margin as Record<string, unknown> | undefined) },
      paper_bgcolor: "#FFFFFF",
      plot_bgcolor: "#FFFFFF",
      font: {
        family: "IBM Plex Sans, -apple-system, BlinkMacSystemFont, sans-serif",
        size: 11.5,
        color: "#334155",
      },
      hoverlabel: {
        bgcolor: "#0F2942",
        bordercolor: "#0F2942",
        font: { color: "#FFFFFF", size: 11.5, family: "IBM Plex Sans, sans-serif" },
      },
      legend: {
        orientation: "h",
        yanchor: "bottom",
        y: 1.02,
        xanchor: "left",
        x: 0,
        font: { size: 11, color: "#475569" },
        ...(layout.legend as Record<string, unknown> | undefined),
      },
      xaxis: {
        gridcolor: CHART_COLORS.grid,
        linecolor: CHART_COLORS.axis,
        zerolinecolor: "#CBD5E1",
        tickfont: { size: 10.5, color: "#475569" },
        ...(layout.xaxis as Record<string, unknown> | undefined),
      },
      yaxis: {
        gridcolor: CHART_COLORS.grid,
        linecolor: CHART_COLORS.axis,
        zerolinecolor: "#94A3B8",
        tickfont: { size: 10.5, color: "#475569" },
        ...(layout.yaxis as Record<string, unknown> | undefined),
      },
      ...layout,
    };
    // Preserve deep-merged axes/margins/legend after spread
    mergedLayout.margin = { t: 26, r: 18, b: 44, l: 58, ...(layout.margin as Record<string, unknown> | undefined) };
    mergedLayout.xaxis = {
      gridcolor: CHART_COLORS.grid,
      linecolor: CHART_COLORS.axis,
      zerolinecolor: "#CBD5E1",
      tickfont: { size: 10.5, color: "#475569" },
      ...(layout.xaxis as Record<string, unknown> | undefined),
    };
    mergedLayout.yaxis = {
      gridcolor: CHART_COLORS.grid,
      linecolor: CHART_COLORS.axis,
      zerolinecolor: "#94A3B8",
      tickfont: { size: 10.5, color: "#475569" },
      ...(layout.yaxis as Record<string, unknown> | undefined),
    };

    const config = {
      responsive: true,
      displaylogo: false,
      displayModeBar: "hover",
      modeBarButtonsToRemove: [
        "lasso2d",
        "select2d",
        "autoScale2d",
        "toggleSpikelines",
        "hoverClosestCartesian",
        "hoverCompareCartesian",
      ],
    };

    import("plotly.js-dist-min").then((mod) => {
      if (!active || !containerRef.current) return;
      const Plotly = mod.default || mod;
      plotlyRef.current = Plotly;
      Plotly.react(containerRef.current, data, mergedLayout, config);

      if (onPointClick) {
        const node = containerRef.current as any;
        node.removeAllListeners?.("plotly_click");
        node.on?.("plotly_click", (evt: any) => {
          if (evt?.points?.[0]) {
            onPointClick(evt.points[0]);
          }
        });
      }
    });

    const ro = new ResizeObserver(() => {
      if (plotlyRef.current && containerRef.current) {
        plotlyRef.current.Plots.resize(containerRef.current);
      }
    });
    ro.observe(el);

    return () => {
      active = false;
      ro.disconnect();
    };
  }, [data, layout, height, onPointClick]);

  useEffect(() => {
    const el = containerRef.current;
    return () => {
      if (plotlyRef.current && el) {
        plotlyRef.current.purge(el);
      }
    };
  }, []);

  return <div ref={containerRef} className={`w-full ${className}`} style={{ minHeight: height }} />;
}
