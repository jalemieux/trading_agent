"use client";

import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import type { PortfolioSnapshot } from "@/lib/types";

const ranges = [
  { label: "1D", hours: 24 },
  { label: "1W", hours: 168 },
  { label: "1M", hours: 720 },
  { label: "ALL", hours: 8760 },
];

export default function PortfolioPage() {
  const [data, setData] = useState<PortfolioSnapshot[]>([]);
  const [hours, setHours] = useState(168);

  useEffect(() => {
    fetch(`/api/portfolio?hours=${hours}`).then((r) => r.json()).then(setData);
  }, [hours]);

  const latest = data[data.length - 1];
  const first = data[0];
  const change = latest && first ? latest.total_value_usd - first.total_value_usd : 0;
  const changePct = first && first.total_value_usd !== 0 ? (change / first.total_value_usd) * 100 : 0;

  // Drawdown calculation
  let peak = 0;
  let maxDrawdown = 0;
  for (const snap of data) {
    if (snap.total_value_usd > peak) peak = snap.total_value_usd;
    const dd = peak > 0 ? ((peak - snap.total_value_usd) / peak) * 100 : 0;
    if (dd > maxDrawdown) maxDrawdown = dd;
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Portfolio</h1>

      <div className="flex gap-2">
        {ranges.map((r) => (
          <button
            key={r.label}
            onClick={() => setHours(r.hours)}
            className={`rounded px-3 py-1 text-sm ${hours === r.hours ? "bg-zinc-700 text-zinc-100" : "bg-zinc-900 text-zinc-400"}`}
          >
            {r.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-sm text-zinc-400">Total Value</p>
          <p className="mt-1 text-2xl font-semibold">${latest?.total_value_usd.toFixed(2) ?? "\u2014"}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-sm text-zinc-400">Change</p>
          <p className={`mt-1 text-2xl font-semibold ${change >= 0 ? "text-green-400" : "text-red-400"}`}>
            {change >= 0 ? "+" : ""}${change.toFixed(2)} ({changePct.toFixed(1)}%)
          </p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-sm text-zinc-400">Realized P&L</p>
          <p className="mt-1 text-2xl font-semibold">${latest?.realized_pnl_cumulative.toFixed(2) ?? "\u2014"}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-sm text-zinc-400">Max Drawdown</p>
          <p className="mt-1 text-2xl font-semibold text-red-400">-{maxDrawdown.toFixed(1)}%</p>
        </div>
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4" style={{ height: 400 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis
              dataKey="timestamp"
              stroke="#71717a"
              tickFormatter={(t) => new Date(t).toLocaleDateString()}
            />
            <YAxis stroke="#71717a" tickFormatter={(v) => `$${v}`} />
            <Tooltip
              contentStyle={{ backgroundColor: "#18181b", border: "1px solid #3f3f46" }}
              labelFormatter={(t) => new Date(t).toLocaleString()}
              formatter={(v) => [`$${Number(v).toFixed(2)}`, "Value"]}
            />
            <Line type="monotone" dataKey="total_value_usd" stroke="#22c55e" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
