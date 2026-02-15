"use client";

import { useEffect, useState } from "react";
import type { Order } from "@/lib/types";

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);

  useEffect(() => {
    fetch("/api/orders?limit=200").then((r) => r.json()).then(setOrders);
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Orders</h1>

      <div className="overflow-x-auto rounded-lg border border-zinc-800">
        <table className="w-full text-sm">
          <thead className="border-b border-zinc-800 bg-zinc-900">
            <tr>
              <th className="px-4 py-2 text-left text-zinc-400">Time</th>
              <th className="px-4 py-2 text-left text-zinc-400">Product</th>
              <th className="px-4 py-2 text-left text-zinc-400">Side</th>
              <th className="px-4 py-2 text-left text-zinc-400">Type</th>
              <th className="px-4 py-2 text-left text-zinc-400">Status</th>
              <th className="px-4 py-2 text-right text-zinc-400">Qty</th>
              <th className="px-4 py-2 text-right text-zinc-400">Fill Price</th>
              <th className="px-4 py-2 text-right text-zinc-400">Fee</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                <td className="px-4 py-2 text-zinc-400">{new Date(o.created_at).toLocaleString()}</td>
                <td className="px-4 py-2">{o.product_id}</td>
                <td className={`px-4 py-2 ${o.side === "BUY" ? "text-green-400" : "text-red-400"}`}>{o.side}</td>
                <td className="px-4 py-2">{o.type}</td>
                <td className="px-4 py-2">
                  <span className={`rounded px-2 py-0.5 text-xs ${
                    o.status === "FILLED" ? "bg-green-950 text-green-400" :
                    o.status === "FAILED" ? "bg-red-950 text-red-400" :
                    "bg-yellow-950 text-yellow-400"
                  }`}>{o.status}</span>
                </td>
                <td className="px-4 py-2 text-right">{o.filled_qty?.toFixed(6) ?? "\u2014"}</td>
                <td className="px-4 py-2 text-right">{o.filled_price ? `$${o.filled_price.toFixed(2)}` : "\u2014"}</td>
                <td className="px-4 py-2 text-right">{o.fee ? `$${o.fee.toFixed(4)}` : "\u2014"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
