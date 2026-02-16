import Database from "better-sqlite3";
import path from "path";

let db: Database.Database | null = null;

export function getDb(): Database.Database {
  if (!db) {
    const dbPath = process.env.DB_PATH || path.resolve(process.cwd(), "../trading_bot.db");
    db = new Database(dbPath, { readonly: true });
  }
  return db;
}
