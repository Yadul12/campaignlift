export interface GlobalFilters {
  start_date: string;
  end_date: string;
  campaign_id: string;
  channel_id: string;
  segment_id: string;
  route_market_id: string;
  experiment_type: string;
  campaign_type: string;
}

export const EMPTY_FILTERS: GlobalFilters = {
  start_date: "",
  end_date: "",
  campaign_id: "",
  channel_id: "",
  segment_id: "",
  route_market_id: "",
  experiment_type: "",
  campaign_type: "",
};

export function buildFilterQueryString(
  filters: Partial<GlobalFilters>,
  extra?: Record<string, string | number | boolean | undefined | null>
): string {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && String(v).trim() !== "") {
      params.set(k, String(v));
    }
  });
  if (extra) {
    Object.entries(extra).forEach(([k, v]) => {
      if (v !== undefined && v !== null && String(v).trim() !== "") {
        params.set(k, String(v));
      }
    });
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const err = await res.json();
      msg = err.detail || err.error || msg;
    } catch {
      // ignore non-JSON body
    }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
    signal,
  });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const err = await res.json();
      msg = err.detail || err.error || msg;
    } catch {
      // ignore
    }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json() as Promise<T>;
}

export function triggerFileDownload(apiPath: string): void {
  const link = document.createElement("a");
  link.href = `/api/v1${apiPath}`;
  link.setAttribute("download", "");
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}
