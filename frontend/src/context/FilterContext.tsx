"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { apiGet, EMPTY_FILTERS, GlobalFilters } from "@/lib/api";

export interface FilterOptions {
  dataset_label: string;
  metadata: Record<string, string>;
  date_bounds: { min_date: string; max_date: string };
  channels: { channel_id: number; channel_code: string; channel_name: string; cost_model: string }[];
  segments: { segment_id: number; segment_code: string; segment_name: string; target_margin_tier: string; incentive_affinity: string }[];
  routes: { route_market_id: number; market_code: string; market_region: string; haul_type: string; avg_base_fare: number; load_factor_baseline: number }[];
  campaigns: { campaign_id: number; campaign_code: string; campaign_name: string; campaign_type: string; experiment_type: string; start_date: string; end_date: string }[];
  campaign_types: string[];
  experiment_types: string[];
}

interface FilterContextValue {
  filters: GlobalFilters;
  options: FilterOptions | null;
  optionsLoading: boolean;
  optionsError: string | null;
  setFilter: <K extends keyof GlobalFilters>(key: K, value: GlobalFilters[K]) => void;
  setMultipleFilters: (patch: Partial<GlobalFilters>) => void;
  resetFilters: () => void;
  activeFilterCount: number;
}

const FilterContext = createContext<FilterContextValue | null>(null);

export function FilterProvider({ children }: { children: React.ReactNode }) {
  const [filters, setFilters] = useState<GlobalFilters>(EMPTY_FILTERS);
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(true);
  const [optionsError, setOptionsError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    apiGet<FilterOptions>("/filters", controller.signal)
      .then((data) => {
        setOptions(data);
        setOptionsError(null);
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          setOptionsError(err.message || "Failed to load filter dimensions");
        }
      })
      .finally(() => setOptionsLoading(false));
    return () => controller.abort();
  }, []);

  const setFilter = useCallback(<K extends keyof GlobalFilters>(key: K, value: GlobalFilters[K]) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }, []);

  const setMultipleFilters = useCallback((patch: Partial<GlobalFilters>) => {
    setFilters((prev) => ({ ...prev, ...patch }));
  }, []);

  const resetFilters = useCallback(() => {
    setFilters(EMPTY_FILTERS);
  }, []);

  const activeFilterCount = useMemo(
    () => Object.values(filters).filter((v) => v.trim() !== "").length,
    [filters]
  );

  const value = useMemo(
    () => ({
      filters,
      options,
      optionsLoading,
      optionsError,
      setFilter,
      setMultipleFilters,
      resetFilters,
      activeFilterCount,
    }),
    [filters, options, optionsLoading, optionsError, setFilter, setMultipleFilters, resetFilters, activeFilterCount]
  );

  return <FilterContext.Provider value={value}>{children}</FilterContext.Provider>;
}

export function useFilters(): FilterContextValue {
  const ctx = useContext(FilterContext);
  if (!ctx) {
    throw new Error("useFilters must be used inside FilterProvider");
  }
  return ctx;
}
