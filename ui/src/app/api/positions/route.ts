import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";
import type { Position } from "@/lib/types";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const status = searchParams.get("status"); // "OPEN", "CLOSED", or null for all

  const db = getDb();
  let rows;
  if (status) {
    rows = db.prepare("SELECT * FROM positions WHERE status = ? ORDER BY opened_at DESC").all(status);
  } else {
    rows = db.prepare("SELECT * FROM positions ORDER BY opened_at DESC").all();
  }
  return NextResponse.json(rows as Position[]);
}
