"use client";

import { useEffect, useState } from "react";

interface SummaryData {
  kill_switch: { active: number; reason: string | null; activated_at: string | null };
  daily_summary: { date: string; total_pnl: number; num_trades: number; fees_paid: number };
  open_positions: Array<{
    id: string; product_id: string; entry_price: number; quantity: number; status: string;
  }>;
  latest_price: { price: number; timestamp: string } | null;
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <p className="text-sm text-zinc-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {sub && <p className="mt-1 text-xs text-zinc-500">{sub}</p>}
    </div>
  );
}

export default function OverviewPage() {
  const [data, setData] = useState<SummaryData | null>(null);

  useEffect(() => {
    const load = () => fetch("/api/summary").then((r) => r.json()).then(setData);
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  if (!data) return <p className="text-zinc-500">Loading...</p>;

  const pos = data.open_positions[0];
  const price = data.latest_price?.price ?? 0;
  const unrealizedPnl = pos ? (price - pos.entry_price) * pos.quantity : 0;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Overview</h1>

      {data.kill_switch.active ? (
        <div className="rounded-lg border border-red-800 bg-red-950 p-4 text-red-300">
          Kill switch ACTIVE: {data.kill_switch.reason}
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Current Price" value={price ? `$${price.toLocaleString()}` : "\u2014"} sub={data.latest_price?.timestamp} />
        <StatCard label="Daily P&L" value={`$${data.daily_summary.total_pnl.toFixed(2)}`} sub={`${data.daily_summary.num_trades} trades`} />
        <StatCard label="Fees Today" value={`$${data.daily_summary.fees_paid.toFixed(2)}`} />
        <StatCard
          label="Unrealized P&L"
          value={pos ? `$${unrealizedPnl.toFixed(2)}` : "\u2014"}
          sub={pos ? `${pos.quantity.toFixed(6)} @ $${pos.entry_price.toFixed(2)}` : "No open position"}
        />
      </div>

      {pos && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <h2 className="mb-2 text-lg font-semibold">Open Position</h2>
          <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
            <div><span className="text-zinc-400">Product:</span> {pos.product_id}</div>
            <div><span className="text-zinc-400">Entry:</span> ${pos.entry_price.toFixed(2)}</div>
            <div><span className="text-zinc-400">Qty:</span> {pos.quantity.toFixed(6)}</div>
            <div><span className="text-zinc-400">Value:</span> ${(pos.quantity * price).toFixed(2)}</div>
          </div>
        </div>
      )}
    </div>
  );
}
