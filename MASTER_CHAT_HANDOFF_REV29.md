# MASTER CHAT HANDOFF REV29

Tanggal handoff: 2026-05-25 Asia/Jakarta

Project: BISMILLAH SUPER TRADING TERMINAL
Repository: https://github.com/agungprabowospsi-dev/BISMILLAH-SUPER-TRADING-TERMINAL
Frontend deploy: https://bismillah-super-trading-terminal.vercel.app
Backend API: https://backend-production-daed.up.railway.app
Local dev URL: http://127.0.0.1:5173/

## Tujuan Utama

Terminal ini dibangun sebagai decision-support trading system untuk IDX yang menyatukan:

- Screener untuk menemukan kandidat saham.
- Analytical untuk membaca setup, engine score, RAG/Knowledge Base, historical memory, SL/TP, dan keputusan GO/WAIT/NO GO.
- Monitoring untuk mengawasi posisi aktif dengan konteks analytic, engine monitoring, broker behavior, historical memory, dan warning system.
- Knowledge Base yang berisi literature trading sebagai referensi engine.
- Historical learning 15 tahun sebagai empirical memory tambahan.
- Orderbook sebagai execution sharpening layer, bukan pengganti keputusan engine existing.

Prinsip penting: jangan membuat engine baru yang menggantikan keputusan existing tanpa alasan. Penambahan baru harus bersifat integratif dan additive.

## Status GitHub Terakhir

Branch utama: main
Status terakhir: sudah tersambung dan merged ke GitHub.

PR penting yang sudah merged:

- PR #7: Integrate analytic context into monitoring.
- PR #8: Fix monitoring enhancement intraday mode.
- PR #9: Complete monitoring integration contract.
- PR #10: Add fast intraday backtest scoring.
- PR #11: Add orderbook execution overlay.

Commit terakhir untuk Orderbook overlay:

- `961f161a2e38d90a0ef9ff5d9b7d1c8c228fc724`

## Prinsip Integrasi Engine

Alur terminal yang harus dijaga:

```text
Screener memilih kandidat
        ↓
Analytical memahami setup dan keputusan
        ↓
Orderbook menajamkan cara eksekusi
        ↓
Monitoring mengawasi posisi aktif
```

Orderbook tidak boleh mengubah GO menjadi NO GO secara absolut. Orderbook hanya memberi panduan eksekusi:

- GO Market jika trigger existing terpenuhi, spread sehat, dan ask tersapu.
- GO Limit Pullback jika setup valid tetapi entry lebih ideal menunggu bid support.
- Wait Confirmation jika liquidity belum mendukung.
- Wait Spread Tighten jika spread terlalu lebar.
- Wait Ask Absorption jika ask wall masih berat.

Policy backend eksplisit:

```text
additive_only_no_decision_override
```

## Lokasi Orderbook Yang Baru

### Di Analytical UI

File:

`frontend/src/components/analytic/AnalyticPage.jsx`

Lokasi:

- `orderbookExecution` dibaca di sekitar line 155.
- Kartu UI muncul di sekitar line 453.
- Letaknya tepat setelah kartu `Executable Setup Plan`.
- Nama kartu: `Orderbook Execution Overlay`.

Isi kartu:

- Execution recommendation.
- Bias.
- Spread.
- Bid/Ask.
- Spread percent.
- Limit Entry.
- Ask Trigger.
- Reason.
- Badge `Additive`.

Jadi di Analytical, urutannya secara visual:

```text
Setup Decision
Phase 2
Market Context
Setup Type
Executable Setup Plan
Orderbook Execution Overlay
15Y Historical Memory
Win Probability
Trade Setup
```

### Di Monitoring UI

File:

`frontend/src/components/monitoring/MonitoringPage.jsx`

Lokasi:

- Orderbook execution dari analytic context dibaca di sekitar line 600.
- Label UI: `Orderbook Execution`.
- Status engine `Orderbook ACTIVE/OFF` muncul di sekitar line 672.

Letaknya:

- Di dalam blok `Analytic Decision`.
- Setelah setup/order/trigger/invalidation.
- Sebelum `15Y Historical Memory` dan `Monitoring Engine Context`.

## Backend Orderbook

File utama:

`backend/app/engines/orderbook_microstructure.py`

Fungsi utama:

- `normalize_orderbook(raw)`
- `build_orderbook_execution_overlay(raw_orderbook, action_plan, mode)`

Kemampuan:

- Membaca top-of-book.
- Membaca top-10 bid/ask style seperti Invezgo attachment.
- Menghitung:
  - best bid,
  - best ask,
  - spread percent,
  - bid/ask ratio,
  - support wall,
  - resistance wall,
  - fake bid wall,
  - fake ask wall,
  - liquidity bias,
  - spread health,
  - suggested limit entry,
  - suggested market trigger.

Output contoh:

```json
{
  "available": true,
  "execution_recommendation": "GO_LIMIT_PULLBACK",
  "execution_style": "LIMIT",
  "liquidity_bias": "bid_dominant",
  "spread_health": "healthy",
  "bid_ask_ratio": 2.08,
  "suggested_limit_entry": 6475,
  "support_wall_price": 6400,
  "resistance_wall_price": 6500,
  "reason": "Bid support dominan; entry lebih tajam dengan limit di area bid support.",
  "overlay_policy": "additive_only_no_decision_override"
}
```

## Analytical Integration

File:

`backend/app/api/analytic.py`

Perubahan utama:

- Analytical prefetch orderbook dari Invesgo.
- Orderbook dikirim ke `run_all_engines`.
- Setelah `action_plan` terbentuk, backend membuat `orderbook_execution`.
- `orderbook_execution` dimasukkan ke:
  - `result["orderbook_execution"]`
  - `action_plan["orderbook_execution"]`
  - prompt AI rationale supaya AI menyebut cara eksekusi jika relevan.

Penting:

- Analytical tetap pemilik setup dan GO/WAIT/NO GO.
- Orderbook hanya pemilik execution overlay.

## Monitoring Integration

File:

`backend/app/api/monitoring.py`

Perubahan utama:

- Monitoring mengambil orderbook Invesgo.
- Fallback ke intraday top-of-book jika orderbook lengkap tidak tersedia.
- Monitoring engine context mengembalikan:
  - `orderbook_included`
  - `orderbook_execution`
  - `engine_details.OrderbookEngine`

Monitoring tetap menerima analytic context dari Analytical, termasuk:

- `go_no_go`
- `go_confidence`
- `action_plan`
- `orderbook_execution`
- `empirical_memory`
- `setup_type`
- `setup_reason`

## Knowledge Base Dan Literature

Knowledge Base berisi 13 literature/buku yang sebelumnya sudah diaudit. Prinsipnya:

- Literature menjadi referensi engine.
- Literature tidak berdiri sendiri sebagai keputusan final.
- KB harus selaras dengan setup type:
  - breakout,
  - pullback,
  - reversal,
  - continuation,
  - retest,
  - failed breakout,
  - accumulation,
  - distribution,
  - markup,
  - markdown.

KB dipakai sebagai RAG/context enrichment, bukan pengganti data market.

## Historical Learning 15 Tahun

User ingin terminal memanfaatkan data 15 tahun Invezgo untuk:

- mempelajari pola win dan lose,
- menyimpan empirical memory,
- menjadi literature referensi tambahan,
- menghemat token API Invezgo dan AI,
- memperkuat screening, analytic, dan monitoring.

Sudah ada konsep dan implementasi awal `empirical_memory` di Analytical dan Monitoring.

Prinsip:

- Historical memory tidak boleh membuat keputusan sendirian.
- Historical memory menjadi confidence modifier dan warning.
- Jika sample kurang, tampilkan sebagai learning/reference only.
- Jika sample kuat, gunakan sebagai support/warning setup.

## Backtest Intraday

User sudah meminta stop backtest.

Jangan jalankan backtest lagi kecuali user eksplisit meminta.

Hasil backtest intraday terakhir yang pernah dijalankan:

- Job completed: `bt_531a8a46`
- Mode: intraday
- Timeframe: 1h
- Period: 1y
- Universe: 20
- Signal engine: `fast_historical_score`
- Total trades: 391
- Winrate: 27.3 percent
- Profit factor: 2.07
- Expectancy: -0.45 percent
- Max drawdown: 78.2 percent

Interpretasi:

- Hasil belum layak dijadikan sistem entry final.
- User tidak setuju filter terlalu ketat.
- Jangan membangun ulang filter baru tanpa diskusi.
- Analytical sudah punya banyak filter/setup logic, jadi perbaikan harus lewat kalibrasi dan integrasi, bukan duplikasi.

## Current Important User Preferences

- Bahasa utama: Indonesia.
- User sering memanggil assistant dengan "akhi".
- User ingin diskusi dulu untuk keputusan besar.
- Jangan menjalankan backtest tanpa izin.
- Jangan mengganti engine existing jika hanya perlu enhancement.
- Semua perubahan sebaiknya langsung tersambung ke GitHub.
- Untuk orderbook: "jangan ganti apa pun yang existing, orderbook menambah ketajaman."

## Validasi Terakhir

Perubahan Orderbook overlay sudah diverifikasi dengan:

```powershell
python -m py_compile backend/app/engines/orderbook_microstructure.py backend/app/engines/execution_engines.py backend/app/api/analytic.py backend/app/api/monitoring.py
```

```powershell
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m unittest backend.tests.test_orderbook_microstructure backend.tests.test_monitoring_e2e_regression
```

```powershell
npm run build
```

Browser lokal reload:

```text
http://127.0.0.1:5173/
```

Result:

- Backend compile OK.
- Tests OK.
- Frontend build OK.
- Browser reload OK.
- No console error.

## Recommended Next Steps

Prioritas berikutnya sebaiknya:

1. Test manual Analytical dengan ticker yang punya orderbook aktif.
2. Pastikan kartu `Orderbook Execution Overlay` muncul setelah `Executable Setup Plan`.
3. Kirim posisi ke Monitoring.
4. Pastikan di Monitoring ada `Orderbook Execution` dalam blok `Analytic Decision`.
5. Setelah itu diskusikan kalibrasi:
   - kapan GO Market,
   - kapan GO Limit Pullback,
   - kapan Wait Confirmation,
   - kapan spread terlalu lebar.

Jangan langsung mengubah score/filter utama sebelum user menyetujui desain keputusan.

## Prompt Pembuka Untuk Chat Baru

Gunakan teks ini untuk memulai chat baru:

```text
Kamu adalah Codex yang melanjutkan project BISMILLAH SUPER TRADING TERMINAL.

Baca MASTER_CHAT_HANDOFF_REV29.md sebagai konteks utama.

Project ini adalah IDX trading terminal dengan Screener, Analytical, Monitoring, Knowledge Base literature, Historical Learning 15 tahun, dan Orderbook Execution Overlay.

Prinsip penting:
- Jangan mengganti engine existing tanpa diskusi.
- Orderbook hanya menambah ketajaman eksekusi, bukan mengganti GO/WAIT/NO GO.
- Jangan menjalankan backtest kecuali saya minta eksplisit.
- Semua perubahan harus selaras Screener -> Analytical -> Monitoring.
- Jika membuat perubahan kode, sambungkan ke GitHub melalui branch/PR/merge.

Tugas pertama: pahami struktur repo dan status terakhir, lalu bantu saya lanjutkan dari kondisi terakhir.
```

