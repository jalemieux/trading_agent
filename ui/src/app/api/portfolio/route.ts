import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const hours = parseInt(searchParams.get("hours") || "168"); // default 7 days

  const db = getDb();
  const rows = db.prepare(
    "SELECT * FROM portfolio_snapshots WHERE timestamp >= datetime('now', ?) ORDER BY timestamp ASC"
  ).all(`-${hours} hours`);
  return NextResponse.json(rows);
}
