"use client";

import { useEffect, useState } from "react";
import type { PredictionRecord, NewsRecord } from "@/lib/types";

interface PredictionWithNews extends PredictionRecord {
  news: NewsRecord[];
}

export default function PredictionsPage() {
  const [predictions, setPredictions] = useState<PredictionWithNews[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetch("/api/predictions?limit=100").then((r) => r.json()).then(setPredictions);
  }, []);

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Predictions</h1>

      <div className="space-y-2">
        {predictions.map((p) => (
          <div key={p.id} className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <span className={`rounded px-2 py-0.5 text-sm font-medium ${
                  p.action === "BUY" ? "bg-green-950 text-green-400" :
                  p.action === "SELL" ? "bg-red-950 text-red-400" :
                  "bg-zinc-800 text-zinc-400"
                }`}>{p.action}</span>
                <span className="text-zinc-400">{p.product_id}</span>
                <span className="text-sm text-zinc-500">
                  Current: ${p.current_price.toFixed(2)} &rarr; Target: ${p.predicted_price?.toFixed(2) ?? "\u2014"}
                </span>
              </div>
              <div className="flex items-center gap-4 text-sm text-zinc-500">
                <span>{p.model}</span>
                <span>{new Date(p.timestamp).toLocaleString()}</span>
              </div>
            </div>

            {p.reasoning && (
              <p className="mt-2 text-sm text-zinc-300">{p.reasoning}</p>
            )}

            {p.news.length > 0 && (
              <button onClick={() => toggle(p.id)} className="mt-2 text-xs text-zinc-500 hover:text-zinc-300">
                {expanded.has(p.id) ? "Hide" : "Show"} {p.news.length} headlines
              </button>
            )}

            {expanded.has(p.id) && (
              <ul className="mt-2 space-y-1 border-l-2 border-zinc-800 pl-3">
                {p.news.map((n) => (
                  <li key={n.id} className="text-sm text-zinc-400">{n.headline}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
