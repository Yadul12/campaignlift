"use client";

import React from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

export function Panel({
  title,
  subtitle,
  action,
  children,
  className = "",
  noPadding = false,
}: {
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  noPadding?: boolean;
}) {
  return (
    <section className={`bg-white border border-[#E2E6EC] rounded-[5px] ${className}`}>
      {(title || action) && (
        <div className="flex items-start justify-between gap-4 px-4 py-3 border-b border-[#EEF1F5]">
          <div className="min-w-0">
            {title && (
              <h2 className="text-[13.5px] font-semibold tracking-[-0.01em] text-[#0F1E2E] leading-snug">
                {title}
              </h2>
            )}
            {subtitle && (
              <p className="text-[11.5px] text-[#64748B] mt-0.5 leading-snug">{subtitle}</p>
            )}
          </div>
          {action && <div className="shrink-0 flex items-center gap-2">{action}</div>}
        </div>
      )}
      <div className={noPadding ? "" : "p-4"}>{children}</div>
    </section>
  );
}

export interface MetricItem {
  label: string;
  value: string;
  sublabel?: string;
  tone?: "default" | "positive" | "negative" | "warning" | "navy";
}

export function MetricStrip({ items, columns = 6 }: { items: MetricItem[]; columns?: number }) {
  const gridCols =
    columns === 4
      ? "grid-cols-2 lg:grid-cols-4"
      : columns === 5
      ? "grid-cols-2 lg:grid-cols-5"
      : "grid-cols-2 md:grid-cols-3 xl:grid-cols-6";

  const toneClass: Record<NonNullable<MetricItem["tone"]>, string> = {
    default: "text-[#0F1E2E]",
    navy: "text-[#0F2942]",
    positive: "text-[#0F766E]",
    negative: "text-[#B91C1C]",
    warning: "text-[#B45309]",
  };

  return (
    <div className={`bg-white border border-[#E2E6EC] rounded-[5px] grid ${gridCols} divide-y md:divide-y-0 md:divide-x divide-[#EEF1F5]`}>
      {items.map((item) => (
        <div key={item.label} className="px-3.5 py-2.5 min-w-0 flex flex-col justify-between">
          <div className="text-[10px] font-semibold uppercase tracking-[0.04em] text-[#64748B] leading-snug">
            {item.label}
          </div>
          <div
            className={`font-mono-num text-[18px] font-semibold tracking-[-0.02em] mt-1 leading-tight whitespace-nowrap ${
              toneClass[item.tone || "default"]
            }`}
          >
            {item.value}
          </div>
          {item.sublabel && (
            <div className="text-[10.5px] text-[#64748B] mt-1 leading-snug">
              {item.sublabel}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export function StatusBadge({
  label,
  variant = "neutral",
}: {
  label: string;
  variant?: "navy" | "positive" | "warning" | "negative" | "neutral" | "cobalt";
}) {
  const styles: Record<string, string> = {
    navy: "bg-[#0F2942] text-white border-[#0F2942]",
    cobalt: "bg-[#EFF6FF] text-[#1E5B94] border-[#BFDBFE]",
    positive: "bg-[#ECFDF5] text-[#0F766E] border-[#A7F3D0]",
    warning: "bg-[#FFFBEB] text-[#B45309] border-[#FDE68A]",
    negative: "bg-[#FEF2F2] text-[#B91C1C] border-[#FECACA]",
    neutral: "bg-[#F1F5F9] text-[#475569] border-[#CBD5E1]",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 text-[10.5px] font-medium rounded-[3px] border whitespace-nowrap ${
        styles[variant] || styles.neutral
      }`}
    >
      {label}
    </span>
  );
}

export function recommendationVariant(status: string | null | undefined) {
  if (!status) return "neutral" as const;
  if (status.includes("Scale")) return "positive" as const;
  if (status.includes("Pause")) return "negative" as const;
  if (status.includes("Reduce") || status.includes("Controlled RCT") || status.includes("Audit")) {
    return "warning" as const;
  }
  return "neutral" as const;
}

export function MethodNote({
  title,
  children,
  tone = "info",
}: {
  title: string;
  children: React.ReactNode;
  tone?: "info" | "warning" | "danger";
}) {
  const styles = {
    info: "bg-[#F8FAFC] border-l-[#1E5B94] border-[#E2E6EC] text-[#334155]",
    warning: "bg-[#FFFBEB] border-l-[#B45309] border-[#FDE68A] text-[#78350F]",
    danger: "bg-[#FEF2F2] border-l-[#B91C1C] border-[#FECACA] text-[#7F1D1D]",
  };
  return (
    <div className={`border border-l-[3px] rounded-[4px] px-3.5 py-2.5 text-[12px] leading-relaxed ${styles[tone]}`}>
      <div className="font-semibold text-[11.5px] uppercase tracking-[0.03em] mb-0.5">{title}</div>
      <div>{children}</div>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col md:flex-row md:items-end justify-between gap-3 pb-3 border-b border-[#E2E6EC]">
      <div>
        <div className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-[#1E5B94]">
          {eyebrow}
        </div>
        <h1 className="text-[20px] font-semibold tracking-[-0.02em] text-[#0F1E2E] mt-0.5">
          {title}
        </h1>
        <p className="text-[12.5px] text-[#475569] mt-0.5 max-w-3xl">{description}</p>
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  );
}

export function LoadingPanel({ lines = 4 }: { lines?: number }) {
  return (
    <div className="bg-white border border-[#E2E6EC] rounded-[5px] p-5 space-y-3 animate-pulse">
      <div className="h-4 bg-[#E2E8F0] rounded w-1/4" />
      {Array.from({ length: lines }).map((_, idx) => (
        <div key={idx} className="h-3 bg-[#EEF1F5] rounded w-full" />
      ))}
    </div>
  );
}

export function ErrorPanel({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="bg-[#FEF2F2] border border-[#FECACA] rounded-[5px] p-4 flex items-start justify-between gap-4">
      <div className="flex items-start gap-2.5">
        <AlertTriangle className="w-4 h-4 text-[#B91C1C] shrink-0 mt-0.5" />
        <div>
          <div className="text-[13px] font-semibold text-[#7F1D1D]">Unable to load analytical view</div>
          <div className="text-[12px] text-[#991B1B] mt-0.5">{message}</div>
        </div>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-[11.5px] font-medium bg-white border border-[#FCA5A5] text-[#991B1B] rounded-[4px] hover:bg-[#FEE2E2] cursor-pointer"
        >
          <RotateCcw className="w-3.5 h-3.5" /> Retry
        </button>
      )}
    </div>
  );
}

export function EmptyPanel({
  title = "No matching campaign records",
  message = "Adjust or reset active global filters to view commercial analytics for this slice.",
  onReset,
}: {
  title?: string;
  message?: string;
  onReset?: () => void;
}) {
  return (
    <div className="bg-white border border-[#E2E6EC] rounded-[5px] py-10 px-6 text-center">
      <div className="text-[13.5px] font-semibold text-[#0F1E2E]">{title}</div>
      <p className="text-[12px] text-[#64748B] mt-1 max-w-md mx-auto">{message}</p>
      {onReset && (
        <button
          onClick={onReset}
          className="mt-3 px-3 py-1.5 text-[12px] font-medium bg-[#0F2942] text-white rounded-[4px] hover:bg-[#1E5B94] cursor-pointer"
        >
          Reset Filters
        </button>
      )}
    </div>
  );
}
