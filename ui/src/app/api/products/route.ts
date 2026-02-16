import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";

export async function GET() {
  const db = getDb();
  const rows = db.prepare("SELECT DISTINCT product_id FROM price_history ORDER BY product_id").all();
  return NextResponse.json((rows as any[]).map((r) => r.product_id));
}
