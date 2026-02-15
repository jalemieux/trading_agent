"use client";

import { useEffect, useState } from "react";
import {
  ComposedChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Scatter,
} from "recharts";
import type { Order, PricePoint } from "@/lib/types";

const ranges = [
  { label: "1H", hours: 1 },
  { label: "6H", hours: 6 },
  { label: "1D", hours: 24 },
  { label: "1W", hours: 168 },
];

interface ChartPoint {
  timestamp: string;
  price: number;
  buy?: number;
  sell?: number;
}

export default function PricesPage() {
  const [prices, setPrices] = useState<PricePoint[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [hours, setHours] = useState(24);

  useEffect(() => {
    fetch(`/api/prices?hours=${hours}`).then((r) => r.json()).then(setPrices);
    fetch("/api/orders?limit=500").then((r) => r.json()).then(setOrders);
  }, [hours]);

  // Merge prices with trade markers
  const filledOrders = orders.filter((o) => o.status === "FILLED" && o.filled_price);
  const chartData: ChartPoint[] = prices.map((p) => ({ timestamp: p.timestamp, price: p.price }));

  // Overlay trades on nearest price point
  for (const order of filledOrders) {
    const entry: ChartPoint = {
      timestamp: order.filled_at || order.created_at,
      price: order.filled_price!,
    };
    if (order.side === "BUY") entry.buy = order.filled_price!;
    else entry.sell = order.filled_price!;
    chartData.push(entry);
  }

  chartData.sort((a, b) => a.timestamp.localeCompare(b.timestamp));

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Price Chart</h1>

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

      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4" style={{ height: 500 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis
              dataKey="timestamp"
              stroke="#71717a"
              tickFormatter={(t) => new Date(t).toLocaleTimeString()}
            />
            <YAxis stroke="#71717a" domain={["auto", "auto"]} tickFormatter={(v) => `$${v.toLocaleString()}`} />
            <Tooltip
              contentStyle={{ backgroundColor: "#18181b", border: "1px solid #3f3f46" }}
              labelFormatter={(t) => new Date(t).toLocaleString()}
              formatter={(v, name) => [`$${Number(v).toLocaleString()}`, name]}
            />
            <Line type="monotone" dataKey="price" stroke="#a1a1aa" dot={false} strokeWidth={1.5} />
            <Scatter dataKey="buy" fill="#22c55e" shape="triangle" />
            <Scatter dataKey="sell" fill="#ef4444" shape="diamond" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
