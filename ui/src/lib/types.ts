export interface Position {
  id: string;
  product_id: string;
  side: string;
  entry_price: number;
  quantity: number;
  status: string;
  realized_pnl: number;
  opened_at: string;
  closed_at: string | null;
}

export interface Order {
  id: string;
  position_id: string | null;
  product_id: string;
  side: string;
  type: string;
  price: number | null;
  quantity: number;
  status: string;
  coinbase_id: string | null;
  filled_price: number | null;
  filled_qty: number | null;
  fee: number | null;
  created_at: string;
  filled_at: string | null;
}

export interface PricePoint {
  product_id: string;
  price: number;
  timestamp: string;
}

export interface PredictionRecord {
  id: string;
  product_id: string;
  action: string;
  predicted_price: number | null;
  current_price: number;
  confidence: number | null;
  reasoning: string | null;
  model: string;
  timestamp: string;
}

export interface NewsRecord {
  id: string;
  prediction_id: string;
  headline: string;
  source: string | null;
  sentiment: string | null;
  timestamp: string;
}

export interface DailySummary {
  date: string;
  total_pnl: number;
  num_trades: number;
  fees_paid: number;
  halted: number;
}

export interface PortfolioSnapshot {
  id: string;
  timestamp: string;
  total_value_usd: number;
  realized_pnl_cumulative: number;
  unrealized_pnl: number;
}

export interface KillSwitchStatus {
  active: boolean;
  reason: string | null;
  activated_at: string | null;
}
