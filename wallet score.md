# Wallet Score v3.1 — Tài liệu tính toán đầy đủ

> Ví dụ minh họa: wallet `8vcR9ZzrGk6nbTHcveSjacDGXjqJR3oVZNUeu3rhTLBg` (Solana, 30d, wac)
> Ngày chạy: 2026-10-11

---

## 1. Tổng quan

Wallet Score là hệ thống chấm điểm 0–100 đánh giá chất lượng giao dịch của một ví tiền dựa trên 4 thành phần chính:

| Thành phần | Trọng số | Mục tiêu đo lường |
|---|---|---|
| **Profitability** (Khả năng sinh lời) | 35% | Ví này kiếm được bao nhiêu so với top leaderboard |
| **Consistency** (Tính nhất quán) | 35% | Win rate, xu hướng 30d/60d, phân bổ lợi nhuận, độ lớn mẫu |
| **Quality** (Chất lượng) | 20% | Tỷ lệ realized, đa dạng lợi nhuận, kỷ luật cắt lỗ, % rug |
| **Activity** (Hoạt động) | 10% | Khối lượng giao dịch, số lệnh, bot penalty |

Kết quả cuối cùng được phân thành **6 hạng (tier)** với màu sắc UI nổi bật, tương phản cao:

| Tier | Ngưỡng | Màu UI | Mã màu |
|---|---|---|---|
| 💎 LEGENDARY | ≥ 95 | Cyan sáng | `#22d3ee` |
| 🟢 ELITE | ≥ 80 | Xanh lá | `#22c55e` |
| 🟡 PRO | ≥ 65 | Vàng | `#facc15` |
| 🟠 ADVANCED | ≥ 50 | Cam | `#fb923c` |
| 🟤 NOVICE | ≥ 30 | Đỏ nhạt | `#f87171` |
| 🔴 RISK | < 30 | Đỏ đậm | `#dc2626` |

---

## 2. Dữ liệu đầu vào — API calls

Mỗi lần chạy Wallet Score gọi 6 endpoint của Birdeye (tổng ~190 CU, leaderboard cache 24h = 0 CU sau lần đầu):

| Step | Endpoint | Method | CU | Mục đích |
|---|---|---|---|---|
| 0 | `/wallet/v2/leaderboard` | GET | 25 (cache 24h) | Lấy top-100 ví có realized PnL cao nhất 30d → làm benchmark percentile |
| 1a | `/wallet/v2/pnl/summary` | GET | 30 | PnL tổng hợp 30d (realized, unrealized, volume, win rate, số lệnh) |
| 1b | `/wallet/v2/pnl/summary` (duration=24h) | GET | 30 | PnL 24h (chẩn đoán, không dùng trong tính điểm) |
| 1c | `/wallet/v2/pnl/summary` (duration=90d) | GET | 30 | PnL 90d → tính xu hướng 30d vs 60d trước |
| 2 | `/wallet/v2/pnl/details` | POST | 30 | PnL chi tiết từng token → detect rug, concentration, severe loss |
| 3 | `/wallet/v2/tx/first-funded` | POST | 40 | Ngày tạo ví (wallet age), block đầu tiên |
| 4 | `/wallet/v2/current-net-worth` | GET | 30 | Net worth hiện tại, danh mục token đang giữ |

**Base URL:** `https://public-api.birdeye.so`

### Dữ liệu trích xuất từ từng API

**Step 1a — PnL Summary 30d:**
- `realized_profit_usd`, `unrealized_usd`, `total_usd`
- `total_invested`, `total_sold`, `current_value` → volume
- `total_trade`, `total_buy`, `total_sell`, `total_win`, `total_loss`
- `win_rate`, `unique_tokens`, `avg_profit_per_trade_usd`

**Step 1c — PnL Summary 90d:**
- `realized_profit_usd` (90d) → suy ra `previous_60d = realized_90d − realized_30d`

**Step 2 — PnL Details (per token):**
- Mỗi token: `realized_profit_usd`, `realized_profit_percent`, `total_percent`, `total_buy`, `total_sell`
- **Rug detection:** token có `total_percent ≤ −50%` HOẶC `realized_profit_percent ≤ −50%`
- **Profit concentration:** vị trí lợi nhuận lớn nhất / tổng lợi nhuận dương
- **Severe loss:** token có `realized_profit_percent ≤ −50%`

**Step 3 — First Funded:**
- `wallet_created_ts_unix`, `wallet_created_block` → wallet age (ngày)

**Step 4 — Portfolio:**
- `current_net_worth_usd`, `portfolio_token_count`

---

## 3. Quy trình tính toán — Cấp cao (không lộ công thức)

```
┌─────────────────────────────────────────────────────────────┐
│  STEP 1: Thu thập dữ liệu từ 6 API (190 CU · 150 CU repeat)  │
│  STEP 2: Kiểm tra hard filters (tx≥20, vol≥$5k, rug≤50%)     │
│          → Chỉ INFORMATIONAL, không phạt alpha               │
│          → Rug đã được phạt trong Quality (granular)         │
│  STEP 3: Tính 4 thành phần (mỗi thành phần 0–100)            │
│          3a. Profitability: leaderboard floor                │
│              top-100 → 85..100, dưới → 10..85, âm → 0        │
│              sau đó trừ dần theo unrealized loss             │
│          3b. Consistency: win rate + xu hướng + phân bổ + mẫu│
│          3c. Quality: realized ratio + đa dạng + cắt lỗ       │
│              sau đó trừ dần theo % rug                       │
│          3d. Activity: volume + số lệnh (trừ bot penalty)    │
│  STEP 4: Alpha = Σ (thành phần × trọng số)                   │
│  STEP 5: Áp dụng sustainability gates (nếu PnL ≤ 0 thì cap)  │
│  STEP 6: Phân tier theo alpha cuối cùng                      │
└─────────────────────────────────────────────────────────────┘
```

### Nguyên tắc thiết kế

- **Không có cliff cứng** — mọi penalty đều tuyến tính (linear), càng xấu càng trừ nhiều.
- **Profitability dùng leaderboard floor** — ví trong top-100 tối thiểu 85đ (rank 1 = 100, rank 100 = 85), dưới top-100 giảm dần 10..85 theo tỷ lệ realized/lb_min, lãi âm → 0.
- **Unrealized loss = lãi chưa chốt bị bốc hơi** — nếu lỗ giấy ≥ lãi đã chốt thì profitability = 0.
- **Rug penalty tuyến tính trong Quality** — 1% rug → −1đ, 25% → −25đ. Hard filter chỉ báo thông tin, không ×0.5 alpha.
- **Ví mới có lãi không bị phạt** — nếu không có lịch sử 60d trước mà đã lãi → trend = 85đ.
- **First-funded cache vĩnh viễn** — wallet age không bao giờ thay đổi → cache CSV riêng, lần sau tiết kiệm 40 CU.

---

## 4. Chi tiết công thức

### 4.1 Hard Filters

Hard filters bây giờ chỉ là **INFORMATIONAL** — không phạt alpha ×0.5 nữa.

| Filter | Ngưỡng | Mục đích |
|---|---|---|
| Số lệnh (`total_trade`) | ≥ 20 | Báo cáo (cũng dùng để tối ưu CU skip API) |
| Volume (`volume_usd`) | ≥ $5,000 | Báo cáo (cũng dùng để tối ưu CU skip API) |
| Tỷ lệ rug (`rug_fraction`) | ≤ 50% | Báo cáo — rug đã được phạt granular trong Quality |

→ Không nhân alpha với 0.5 khi fail. Mọi penalty đều đã được tính granular trong từng thành phần (đặc biệt là Quality cho rug).

### 4.2 Profitability (35%)

**Bước 1 — Leaderboard floor (top-100 làm trần):**

```
rank = số ví trong leaderboard có realized ≥ ví này
N = số ví trong leaderboard (thường 100)
lb_min = giá trị realized nhỏ nhất trong leaderboard (top 100)

if realized <= 0:
    profit_base = 0
elif rank <= N:                          # trong hoặc trên top-100
    profit_base = 100 - 15 × (rank-1) / (N-1)   # 85..100
else:                                    # dưới top-100
    ratio = min(realized / lb_min, 1.0)
    profit_base = 10 + 75 × ratio              # 10..85
```

- Rank #1 (tốt nhất): `100 - 15 × 0/99 = 100`
- Rank #100 (cuối top-100): `100 - 15 × 99/99 = 85`
- Dưới top-100, realized = 50% lb_min: `10 + 75 × 0.5 = 47.5`
- Dưới top-100, realized ≈ 0: `≈ 10`
- Lãi âm: `0`

**Bước 2 — Unrealized loss penalty (tuyến tính):**

```
keep_factor = max(0, 1 − |unrealized_loss| / realized)
profitability = profit_base × keep_factor
```

- |unr| = 0 → giữ 100%
- |unr| = 50% realized → giữ 50%
- |unr| ≥ realized → profitability = 0

### 4.3 Consistency (35%)

```
consistency = 0.20 × win_rate_score
            + 0.40 × trend_score
            + 0.25 × trade_distribution_score
            + 0.15 × sample_confidence_score
```

**win_rate_score** (20%):
```
win_rate_score = clamp(win_rate / 0.60 × 100, 0, 100)
→ 60% win rate = 100đ
```

**trend_score** (40%) — so sánh 30d vs 60d trước:

| Điều kiện | trend_score | Status |
|---|---|---|
| prev60d ≈ 0 (ví mới) & realized > 0 | 85 | NEW_PROFITABLE |
| realized > 0 & prev60d > 0 | 70–100 (tính theo độ ổn định) | SUSTAINABLE |
| realized > 0 & prev60d ≤ 0 | 35 | RECENT_RECOVERY |
| realized ≤ 0 & prev60d > 0 | 15 | RECENT_LOSSES |
| realized ≤ 0 & prev60d ≤ 0 | 0 | UNPROFITABLE |

**trade_distribution_score** (25%):
```
profitable_pos_score = clamp(profitable_positions / closed_positions / 0.60 × 100, 0, 100)
distribution_score = 100 × (1 − profit_concentration)
trade_distribution = 0.60 × profitable_pos_score + 0.40 × distribution_score
```

**sample_confidence_score** (15%):
```
sample_confidence = clamp(log1p(total_trade) / log1p(300) × 100, 0, 100)
→ 300 lệnh = 100đ
```

### 4.4 Quality (20%)

```
quality = 0.35 × realization_score
        + 0.35 × profit_distribution_quality
        + 0.30 × loss_discipline_score
        − rug_penalty_pts
```

**realization_score** (35%):
```
realization = realized / (realized + max(unrealized, 0)) × 100
→ lãi đã chốt / tổng lãi (đã chốt + chưa chốt)
```

**profit_distribution_quality** (35%):
```
= 100 × (1 − profit_concentration)
→ concentration = vị trí lợi nhuận lớn nhất / tổng lợi nhuận dương
```

**loss_discipline_score** (30%):
```
= 100 × (1 − clamp(severe_loss_fraction / 0.30, 0, 1))
→ severe_loss_fraction = số vị trí lỗ >50% / tổng vị trí đã đóng
→ 30% severe loss → loss_discipline = 0
```

**rug_penalty** (trừ thẳng):
```
rug_penalty_pts = rug_fraction × 100
quality = clamp(quality − rug_penalty_pts, 0, 100)
```
- 1% rug → −1đ
- 25% rug → −25đ
- 50% rug → −50đ (hard filter chỉ báo thông tin, không ×0.5)

### 4.5 Activity (10%)

```
vol_score = clamp(log10(volume_usd / 1000) × 20, 0, 100)
tx_confidence = clamp(log1p(total_trade) / log1p(300), 0, 1)
bot_penalty = max(sqrt(300 / total_trade), 0.70)  khi total_trade > 300
            = 1.0                                    khi total_trade ≤ 300

activity = (0.60 × vol_score + 0.40 × tx_confidence × 100) × bot_penalty
```

- Bot penalty floor = 0.70 (vì 300+ lệnh có thể là bot, không phạt quá tay)

### 4.6 Alpha tổng hợp + Sustainability Gates

```
alpha_weighted = profitability × 0.35
               + consistency × 0.35
               + quality × 0.20
               + activity × 0.10

# Hard filters: KHÔNG áp dụng ×0.5 nữa (chỉ báo cáo thông tin)
# Rug đã được phạt granular trong Quality

# Sustainability gates
if realized_30d ≤ 0:        alpha = min(alpha, 39)
if realized_90d ≤ 0:        alpha = min(alpha, 49)
if prev60d ≤ 0 AND |prev60d| > $100:  alpha = min(alpha, 69)

alpha_final = clamp(alpha_weighted, 0, 100)
```

### 4.7 Tier Ranking (6 hạng)

```
α ≥ 95  →  💎 LEGENDARY   (cyan #22d3ee)
α ≥ 80  →  🟢 ELITE       (green #22c55e)
α ≥ 65  →  🟡 PRO         (yellow #facc15)
α ≥ 50  →  🟠 ADVANCED    (orange #fb923c)
α ≥ 30  →  🟤 NOVICE      (light red #f87171)
α < 30  →  🔴 RISK        (red #dc2626)
```

---

## 5. Ví dụ tính toán chi tiết — Wallet `8vcR9ZzrGk…rhTLBg`

### 5.1 Dữ liệu thô từ API

| Metric | Giá trị | Nguồn |
|---|---|---|
| Wallet address | `8vcR9ZzrGk6nbTHcveSjacDGXjqJR3oVZNUeu3rhTLBg` | input |
| Chain | solana | input |
| Duration | 30d | input |
| Wallet age | 6 ngày | Step 3 first-funded |
| Realized PnL (30d) | +$335,500.10 | Step 1a |
| Unrealized PnL | −$57,107.04 | Step 1a |
| Total PnL | +$278,685.80 | Step 1a |
| Volume | $390,644.58 | Step 1a |
| Total trades | 478 | Step 1a |
| Win rate | 33.33% | Step 1a |
| Unique tokens | 3 | Step 1a |
| Current net worth | $87.84 | Step 4 |
| Realized 90d | +$335,500.10 (= 30d) | Step 1c |
| Previous 60d PnL | $0 (= 90d − 30d) | tính từ 90d − 30d |
| Rug tokens | 3 / 4 scanned | Step 2 |
| Rug fraction | 75% | Step 2 |
| Profit concentration | 100% (1 vị trí chiếm hết lợi nhuận) | Step 2 |
| Severe loss positions | 1 / 4 closed | Step 2 |

### 5.2 Hard Filters

| Filter | Ngưỡng | Thực tế | Kết quả |
|---|---|---|---|
| tx ≥ 20 | 20 | 478 | ✅ PASS |
| volume ≥ $5,000 | $5,000 | $390,645 | ✅ PASS |
| rug ≤ 50% | 50% | 75% | ❌ FAIL (info only) |

→ **Hard filter FAIL** (rug 75% > 50%) — chỉ báo cáo, KHÔNG ×0.5 alpha. Rug đã phạt trong Quality.

### 5.3 Profitability (35%)

**Bước 1 — Leaderboard floor:**
```
realized = $335,500
leaderboard top-100 (30d realized, wac)
rank = 58  (58 ví trong leaderboard có realized ≥ $335,500)
N = 100

# rank <= N → trong top-100 → base 85..100
profit_base = 100 - 15 × (58-1) / (100-1)
            = 100 - 15 × 57/99
            = 100 - 15 × 0.5758
            = 100 - 8.64
            = 91.36
```

**Bước 2 — Unrealized penalty:**
```
unrealized = −$56,649
realized = $335,500

keep_factor = max(0, 1 − 56,649 / 335,500)
            = max(0, 1 − 0.1688)
            = 0.8312

profitability = 91.36 × 0.8312 = 75.94
```

→ **Profitability = 75.94 / 100**

### 5.4 Consistency (35%)

**win_rate_score:**
```
win_rate = 33.33%
win_rate_score = clamp(0.3333 / 0.60 × 100, 0, 100)
               = clamp(55.56, 0, 100)
               = 55.56
```

**trend_score:**
```
realized_30d = +$335,500 (positive)
prev_60d = $0 (|prev60d| ≤ $100 → ví mới)
→ NEW_PROFITABLE → trend_score = 85.0
```

**trade_distribution_score:**
```
closed_positions = 4
profitable_positions = 1
profit_concentration = 1.0 (100%)

profitable_pos_score = clamp((1/4) / 0.60 × 100, 0, 100)
                     = clamp(41.67, 0, 100) = 41.67
distribution_score = 100 × (1 − 1.0) = 0

trade_distribution = 0.60 × 41.67 + 0.40 × 0
                   = 25.0
```

**sample_confidence_score:**
```
total_trade = 478
sample_confidence = clamp(log1p(478) / log1p(300) × 100, 0, 100)
                  = clamp(1.0, 0, 100) = 100.0
```

**Consistency:**
```
consistency = 0.20 × 55.56 + 0.40 × 85.0 + 0.25 × 25.0 + 0.15 × 100.0
            = 11.11 + 34.0 + 6.25 + 15.0
            = 66.36
```

→ **Consistency = 66.36 / 100**

### 5.5 Quality (20%)

**realization_score:**
```
realized = $335,500 (positive)
unrealized = −$57,107 (negative → max(unrealized, 0) = 0)
positive_total = 335,500 + 0 = 335,500

realization = 335,500 / 335,500 × 100 = 100.0
```

**profit_distribution_quality:**
```
concentration = 1.0
profit_distribution_quality = 100 × (1 − 1.0) = 0.0
```

**loss_discipline_score:**
```
severe_loss_fraction = 1 / 4 = 0.25
loss_discipline = 100 × (1 − clamp(0.25 / 0.30, 0, 1))
                = 100 × (1 − 0.8333)
                = 16.67
```

**Trừ rug penalty:**
```
rug_fraction = 0.75
rug_penalty_pts = 0.75 × 100 = 75.0

quality_pre = 0.35 × 100.0 + 0.35 × 0.0 + 0.30 × 16.67
            = 35.0 + 0.0 + 5.0
            = 40.0

quality = clamp(40.0 − 75.0, 0, 100) = 0.0
```

→ **Quality = 0.0 / 100** (rug 75% đã làm sạch hết điểm quality)

### 5.6 Activity (10%)

```
volume = $390,645
vol_score = clamp(log10(390,645 / 1000) × 20, 0, 100)
          = clamp(log10(390.645) × 20, 0, 100)
          = clamp(2.592 × 20, 0, 100)
          = clamp(51.8, 0, 100) = 51.8

total_trade = 478
tx_confidence = clamp(log1p(478) / log1p(300), 0, 1) = 1.0

bot_penalty = max(sqrt(300/478), 0.70) = max(0.792, 0.70) = 0.792

activity = (0.60 × 51.8 + 0.40 × 1.0 × 100) × 0.792
         = (31.1 + 40.0) × 0.792
         = 71.1 × 0.792
         = 56.3
```

→ **Activity = 56.33 / 100**

### 5.7 Alpha cuối cùng

```
alpha_weighted = 75.94 × 0.35 + 66.36 × 0.35 + 0.0 × 0.20 + 56.33 × 0.10
               = 26.58 + 23.23 + 0.0 + 5.63
               = 55.44

# Hard filter FAIL (rug 75% > 50%) → KHÔNG áp dụng ×0.5 (chỉ báo cáo)
# Rug đã được phạt trong Quality (0đ)

# Sustainability gates:
#   realized_30d = +$335,500 > 0 → không cap 39
#   realized_90d = +$335,500 > 0 → không cap 49
#   prev60d = $0, |prev60d| ≤ $100 → không cap 69 (ví mới)

alpha_final = 55.44
```

### 5.8 Tier

```
alpha = 55.44 (50 ≤ α < 65)  →  � ADVANCED (#fb923c)
```

---

## 6. Kết quả cuối cùng

| Thành phần | Điểm | Trọng số | Góp phần |
|---|---|---|---|
| Profitability | 75.94 | 35% | 26.58 |
| Consistency | 66.36 | 35% | 23.23 |
| Quality | 0.00 | 20% | 0.00 |
| Activity | 56.33 | 10% | 5.63 |
| **Alpha cuối** | | | **55.44** |
| **Tier** | | | � **ADVANCED** |

### Tại sao ví này chỉ ADVANCED dù lãi +$335K?

1. **Rug 75%** — 3/4 token là rug (lỗ >50%), rug penalty 75đ đã làm sạch quality (0đ).
2. **Profit concentration 100%** — toàn bộ lợi nhuận đến từ 1 token duy nhất → không đa dạng.
3. **Win rate 33%** — thấp so với target 60%.
4. **Ví mới 6 ngày** — không có lịch sử 60d trước, dù trend được tặng 85đ (NEW_PROFITABLE).

### So sánh với ví top leaderboard

Ví `2w3nD9VdSh…DwfB5Q3c` (top leaderboard, +$7.36M realized, 1% rug):
- Profitability ≈ 98 (rank #1, base 100, keep_factor ≈ 0.98)
- Quality ≈ 96 (rug −1đ)
- Alpha ≈ 93 → 🟢 ELITE

Sự khác biệt chính: rug% (1% vs 75%), profit concentration (5% vs 100%), và vị trí leaderboard (#1 vs #58).

---

## 7. Tóm tắt thiết kế v3.1

| Yếu tố | v3 (cũ) | v3.1 (mới) |
|---|---|---|
| Profitability | `realized / leaderboard_max` | leaderboard floor: top-100 → 85..100, dưới → 10..85, âm → 0 |
| Unrealized penalty | trigger 10%, max 50% | tuyến tính `max(0, 1−|unr|/realized)`, |unr|≥realized→0 |
| Rug penalty | cliff cứng | tuyến tính `rug%×100` (1%→−1đ) trong Quality |
| Hard filter penalty | fail bất kỳ → alpha ×0.5 | **bỏ penalty**, chỉ báo cáo thông tin |
| Tier | 4 hạng (ELITE/PRO/NOVICE/RISK) | 6 hạng (LEGENDARY/ELITE/PRO/ADVANCED/NOVICE/RISK) |
| Ví mới | trend=35 (RECENT_RECOVERY) | trend=85 (NEW_PROFITABLE) |
| prev60D gate | cap-69 mọi ví | chỉ cap khi \|prev60d| > $100 |
| First-funded | gọi API mỗi lần (40 CU) | cache vĩnh viễn CSV (0 CU sau lần đầu) |
