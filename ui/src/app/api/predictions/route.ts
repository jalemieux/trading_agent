import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const limit = parseInt(searchParams.get("limit") || "50");

  const db = getDb();
  const predictions = db.prepare("SELECT * FROM predictions ORDER BY timestamp DESC LIMIT ?").all(limit);

  // Attach news to each prediction
  const stmt = db.prepare("SELECT * FROM news_history WHERE prediction_id = ?");
  const result = (predictions as any[]).map((p) => ({
    ...p,
    news: stmt.all(p.id),
  }));

  return NextResponse.json(result);
}
