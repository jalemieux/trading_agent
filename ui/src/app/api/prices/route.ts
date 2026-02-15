import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const product = searchParams.get("product_id") || "BTC-USD";
  const hours = parseInt(searchParams.get("hours") || "24");

  const db = getDb();
  const rows = db.prepare(
    "SELECT * FROM price_history WHERE product_id = ? AND timestamp >= datetime('now', ?) ORDER BY timestamp ASC"
  ).all(product, `-${hours} hours`);
  return NextResponse.json(rows);
}
