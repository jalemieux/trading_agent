"use client";

import { useEffect, useState } from "react";
import type { Position } from "@/lib/types";

export default function PositionsPage() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [filter, setFilter] = useState<string>("");

  useEffect(() => {
    const url = filter ? `/api/positions?status=${filter}` : "/api/positions";
    fetch(url).then((r) => r.json()).then(setPositions);
  }, [filter]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Positions</h1>
        <div className="flex gap-2">
          {["", "OPEN", "CLOSED"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded px-3 py-1 text-sm ${filter === f ? "bg-zinc-700 text-zinc-100" : "bg-zinc-900 text-zinc-400"}`}
            >
              {f || "All"}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-zinc-800">
        <table className="w-full text-sm">
          <thead className="border-b border-zinc-800 bg-zinc-900">
            <tr>
              <th className="px-4 py-2 text-left text-zinc-400">Product</th>
              <th className="px-4 py-2 text-left text-zinc-400">Status</th>
              <th className="px-4 py-2 text-right text-zinc-400">Entry Price</th>
              <th className="px-4 py-2 text-right text-zinc-400">Quantity</th>
              <th className="px-4 py-2 text-right text-zinc-400">Realized P&L</th>
              <th className="px-4 py-2 text-left text-zinc-400">Opened</th>
              <th className="px-4 py-2 text-left text-zinc-400">Closed</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.id} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                <td className="px-4 py-2">{p.product_id}</td>
                <td className="px-4 py-2">
                  <span className={`rounded px-2 py-0.5 text-xs ${p.status === "OPEN" ? "bg-green-950 text-green-400" : "bg-zinc-800 text-zinc-400"}`}>
                    {p.status}
                  </span>
                </td>
                <td className="px-4 py-2 text-right">${p.entry_price.toFixed(2)}</td>
                <td className="px-4 py-2 text-right">{p.quantity.toFixed(6)}</td>
                <td className={`px-4 py-2 text-right ${p.realized_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                  ${p.realized_pnl.toFixed(2)}
                </td>
                <td className="px-4 py-2 text-zinc-400">{new Date(p.opened_at).toLocaleString()}</td>
                <td className="px-4 py-2 text-zinc-400">{p.closed_at ? new Date(p.closed_at).toLocaleString() : "\u2014"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
