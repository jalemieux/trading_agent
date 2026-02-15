import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";

export async function GET() {
  const db = getDb();

  const killSwitch = db.prepare("SELECT active, reason, activated_at FROM kill_switch WHERE id = 1").get();
  const todaySummary = db.prepare("SELECT * FROM daily_summary WHERE date = date('now')").get();
  const openPositions = db.prepare("SELECT * FROM positions WHERE status = 'OPEN'").all();
  const latestPrice = db.prepare("SELECT price, timestamp FROM price_history ORDER BY timestamp DESC LIMIT 1").get();

  return NextResponse.json({
    kill_switch: killSwitch,
    daily_summary: todaySummary || { date: new Date().toISOString().slice(0, 10), total_pnl: 0, num_trades: 0, fees_paid: 0, halted: 0 },
    open_positions: openPositions,
    latest_price: latestPrice,
  });
}
