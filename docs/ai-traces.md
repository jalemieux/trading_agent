# Execution Traces

Step-by-step execution paths with file:line references for every major flow.

---

## Trace 1: Market BUY Order (happy path)

```
1. External publishes OrderRequest(product_id="BTC-USD", side="BUY", order_type="MARKET", quote_size=100.0)
   → event_bus.py:20  publish() dispatches to subscribers of OrderRequest

2. OrderManager._handle_order_request(order)                    order_manager.py:29
   2a. await self._risk.check(order)                            order_manager.py:31
       → risk_manager.py:26  check()
       → risk_manager.py:28  kill_switch.is_active? → False
       → risk_manager.py:35  query daily_summary for today's P&L
       → risk_manager.py:51  order.side=="BUY", quote_size=100 <= max=100? → OK
       → returns True

   2b. self._place_market_order(order)                          order_manager.py:40
       → order_manager.py:87  order.side=="BUY"
       → order_manager.py:88  coinbase.market_buy(client_order_id=order.order_id, product_id="BTC-USD", quote_size="100.0")
       → coinbase_client.py:12  _client.market_order_buy(...)
       → returns {"success": True, "success_response": {"order_id": "cb-123"}}

   2c. cb_order_id = "cb-123"                                   order_manager.py:64
       Poll for fill details (up to 5 attempts, 1s delay):      order_manager.py:70-80
       for attempt in range(5):
         self._coinbase.get_order("cb-123")                     order_manager.py:71
         → coinbase_client.py:48  _client.get_order("cb-123")
         → returns {"order": {"filled_size": "0.002", "average_filled_price": "50000", "total_fees": "0.20"}}
         filled_qty > 0 → break

   2d. filled_price=50000.0, filled_qty=0.002, fee=0.20        order_manager.py:74-76

   2e. await self._persist_order(order, now, coinbase_id="cb-123", ...)  order_manager.py:83-90
       → INSERT INTO orders (...)                                order_manager.py:137-155

   2f. await self._bus.publish(OrderFilled(...))                 order_manager.py:92-102
       → event_bus.py:20  dispatch to PositionTracker._handle_order_filled

3. PositionTracker._handle_order_filled(event)                  position_tracker.py:20
   3a. await self._upsert_order(event)                          position_tracker.py:22
       → position_tracker.py:32  SELECT id FROM orders WHERE id = ?
       → Row exists (OrderManager already inserted it)
       → position_tracker.py:36  UPDATE orders SET status='FILLED', filled_price=50000...

   3b. event.side == "BUY"                                      position_tracker.py:24
       → self._open_or_add_position(event)                      position_tracker.py:25

   3c. SELECT id, entry_price, quantity FROM positions WHERE product_id='BTC-USD' AND status='OPEN'
       → position_tracker.py:54  No existing position found

   3d. pos_id = uuid4()                                         position_tracker.py:71
       INSERT INTO positions (id, product_id, side, entry_price, quantity, status, opened_at)
       VALUES (pos_id, "BTC-USD", "LONG", 50000.0, 0.002, "OPEN", now)
       → position_tracker.py:72-76

   3e. UPDATE orders SET position_id = pos_id WHERE id = order_id  position_tracker.py:79-80

   3f. await self._bus.publish(PositionChanged(status="OPEN", quantity=0.002))  position_tracker.py:86
```

---

## Trace 2: Market SELL Order (closes position)

```
Precondition: open position exists for BTC-USD (pos_id, entry_price=50000, qty=0.002)

1. External publishes OrderRequest(side="SELL", order_type="MARKET", base_size=0.002)

2. OrderManager._handle_order_request                           order_manager.py:29
   2a. risk.check(order) → True                                 risk_manager.py:26
       (SELL orders skip max order size check)                   risk_manager.py:51
   2b. _place_market_order → coinbase.market_sell(base_size="0.002")  order_manager.py:94
   2c. get_order → filled_price=51000, filled_qty=0.002, fee=0.20
   2d. persist, publish OrderFilled

3. PositionTracker._handle_order_filled                          position_tracker.py:20
   3a. _upsert_order(event)                                      position_tracker.py:22
   3b. event.side == "SELL" → _reduce_or_close_position          position_tracker.py:27

   3c. SELECT open position → (pos_id, entry_price=50000, qty=0.002)  position_tracker.py:98
   3d. sell_qty = min(0.002, 0.002) = 0.002                     position_tracker.py:107
       remaining = 0.002 - 0.002 = 0.0                          position_tracker.py:108

   3e. P&L calculation:                                          position_tracker.py:111-120
       pnl = (51000 - 50000) * 0.002 - 0.20 = 1.80
       buy_fee_total = SUM(fee) from orders WHERE position_id=pos_id AND side='BUY' = 0.20
       buy_fee_portion = 0.20 * (0.002 / 0.002) = 0.20
       pnl = 1.80 - 0.20 = 1.60

   3f. remaining (0.0) <= 1e-10 → fully closed                  position_tracker.py:124
       UPDATE positions SET status='CLOSED', quantity=0, realized_pnl=1.60  position_tracker.py:126

   3g. UPDATE orders SET position_id=pos_id WHERE id=order_id    position_tracker.py:141

   3h. Daily summary:                                            position_tracker.py:146
       total_fee = 0.20 (sell) + 0.20 (buy portion) = 0.40
       INSERT INTO daily_summary (date, total_pnl=1.60, num_trades=1, fees_paid=0.40)

   3i. publish PositionChanged(status="CLOSED", quantity=0.0)    position_tracker.py:165
```

---

## Trace 3: Risk Rejection (kill switch)

```
Precondition: kill_switch.is_active == True

1. External publishes OrderRequest(side="BUY", quote_size=50.0)

2. OrderManager._handle_order_request                            order_manager.py:29
   2a. await self._risk.check(order)                             order_manager.py:31
       → risk_manager.py:28  kill_switch.is_active → True
       → risk_manager.py:29  publish RiskViolation(reason="Kill switch is active")
       → returns False

   2b. approved == False → return                                order_manager.py:32-33
       (no Coinbase call, no DB write, no OrderFailed published)
```

---

## Trace 4: Risk Rejection (daily loss → auto kill switch)

```
Precondition: daily_summary has total_pnl = -600.0, max_daily_loss_usd = 500.0

1. External publishes OrderRequest(side="BUY", quote_size=10.0)

2. OrderManager._handle_order_request → risk.check(order)
   2a. kill_switch.is_active → False                             risk_manager.py:28
   2b. SELECT total_pnl FROM daily_summary WHERE date = today    risk_manager.py:36
       → -600.0 <= -500.0 → True                                risk_manager.py:39
   2c. kill_switch.activate("Daily loss $600.00...")             risk_manager.py:40
       → kill_switch.py:27  _active = True
       → kill_switch.py:29  UPDATE kill_switch SET active=1, reason=...
       → kill_switch.py:34  publish KillSwitchActivated
   2d. publish RiskViolation                                     risk_manager.py:43
   2e. return False                                              risk_manager.py:48

   All subsequent orders will hit check #1 (kill switch active).
```

---

## Trace 5: Coinbase API Error

```
1. External publishes OrderRequest(side="BUY", quote_size=50.0)

2. OrderManager._handle_order_request                            order_manager.py:29
   2a. risk.check → True
   2b. _place_market_order → coinbase.market_buy(...)            order_manager.py:88
       Returns: {"success": False, "error_response": {"error": "INSUFFICIENT_FUND"}}

   2c. result.get("success") → False                             order_manager.py:48
       reason = "INSUFFICIENT_FUND"                              order_manager.py:50
       _persist_order(status="FAILED")                           order_manager.py:51
       publish OrderFailed(reason="INSUFFICIENT_FUND")           order_manager.py:52
```

---

## Trace 6: Coinbase Exception (network error)

```
1. External publishes OrderRequest(side="BUY", quote_size=50.0)

2. OrderManager._handle_order_request                            order_manager.py:29
   2a. risk.check → True
   2b. _place_market_order → coinbase.market_buy(...)            order_manager.py:88
       Raises: ConnectionError("timeout")

   2c. except Exception as e:                                    order_manager.py:43
       logger.exception("Failed to place order")                 order_manager.py:44
       publish OrderFailed(reason="timeout")                     order_manager.py:45
       return                                                    order_manager.py:46

   Note: order is NOT persisted to DB in this path.
```

---

## Trace 7: Partial Sell (position stays open)

```
Precondition: open position BTC-USD, entry_price=50000, qty=0.004

1. SELL fill arrives: filled_qty=0.002, filled_price=51000

2. PositionTracker._reduce_or_close_position                    position_tracker.py:97
   2a. sell_qty = min(0.002, 0.004) = 0.002                     position_tracker.py:107
       remaining = 0.004 - 0.002 = 0.002                        position_tracker.py:108

   2b. P&L:
       pnl = (51000 - 50000) * 0.002 - sell_fee - proportional_buy_fee
       buy_fee_portion = total_buy_fees * (0.002 / 0.004) = 50% of buy fees

   2c. remaining (0.002) > 1e-10 → partial close                position_tracker.py:132
       UPDATE positions SET quantity=0.002, realized_pnl += pnl  position_tracker.py:134

   2d. publish PositionChanged(status="OPEN", quantity=0.002)    position_tracker.py:165
```

---

## Trace 8: WebSocket Message (MarketData)

```
1. Coinbase WSClient receives message on background thread
   → calls on_message lambda                                     market_data.py:21

2. _schedule_on_message(msg)                                     market_data.py:24
   → if self._loop exists:
     asyncio.run_coroutine_threadsafe(_on_message(msg), loop)    market_data.py:26

3. _on_message(msg)  [runs on asyncio event loop]                market_data.py:28
   3a. json.loads(msg)                                           market_data.py:30
   3b. data["channel"] == "ticker"?                              market_data.py:34
       If not → return (ignore heartbeats, etc.)
   3c. For each events[].tickers[]:                              market_data.py:38-39
       publish PriceUpdate(product_id, price=float(price_str))   market_data.py:43
```

---

## Startup Trace (main.py)

```
1.  parse_args()                         main.py:27    --strategy, --llm, --model
2.  Settings()                           main.py:52    loads .env
3.  EventBus()                           main.py:53
4.  Database(db_path)                    main.py:57
5.  await db.initialize()                main.py:58    creates tables, seeds kill_switch
6.  KillSwitch(db, bus)                  main.py:62
7.  await kill_switch.initialize()       main.py:63    loads persisted state
8.  RiskManager(db, bus, ks, settings)   main.py:68
9.  CoinbaseClient(key, secret, key_file)  main.py:71
10. OrderManager(db, bus, rm, cb)        main.py:78
11. order_manager.register(bus)          main.py:79    subscribes to OrderRequest
12. PositionTracker(db, bus)             main.py:82
13. position_tracker.register(bus)       main.py:83    subscribes to OrderFilled
14. PortfolioTracker(db, bus, cb, ...)   main.py:86
15. MarketData(bus, key, secret, key_file, db)  main.py:95
16. LLM client from LLM_PROVIDERS[args.llm]    main.py:104-115
17. PriceBuffer(max_size=50)             main.py:118
18. Strategy from STRATEGIES[args.strategy]     main.py:120-138
    - "news" → NewsService injected, NewsPredictionStrategy(llm_client, news_service, **kwargs)
    - "price_only" → PriceOnlyStrategy(llm_client, **kwargs)
19. strategy.register(bus)               main.py:139   subscribes to PriceUpdate
20. Signal handlers registered           main.py:148-154
21. await market_data.start([product_id])  main.py:157
22. await strategy.start()               main.py:158   launches prediction loop task
23. await portfolio_tracker.start()      main.py:159
24. await stop_event.wait()              main.py:163   blocks until SIGINT/SIGTERM
25. await portfolio_tracker.stop()       main.py:166
26. await strategy.stop()                main.py:167
27. await market_data.stop()             main.py:168
28. await db.close()                     main.py:169
```
