# EigenCapital Architecture Diagram

**Last updated:** 2026-07-17

```mermaid
---
title: EigenCapital Paper-Trading System Architecture
---
graph TB
    %% ── Styles ──────────────────────────────────────────────────────
    classDef infra fill:#1a1a2e,stroke:#4a4a8a,stroke-width:2,color:#e0e0ff
    classDef core fill:#16213e,stroke:#0f3460,stroke-width:2,color:#a8d8ea
    classDef service fill:#1b2a3a,stroke:#2d6a4f,stroke-width:2,color:#95d5b2
    classDef feature fill:#2d1b2e,stroke:#6a0dad,stroke-width:2,color:#d8b4fe
    classDef risk fill:#3a1b1b,stroke:#8b0000,stroke-width:2,color:#ffb4b4
    classDef data fill:#1b3a2e,stroke:#006b4a,stroke-width:2,color:#b4e4d0
    classDef frontend fill:#2e2e1b,stroke:#6b6b00,stroke-width:2,color:#e4e4b4
    classDef external fill:#2a2a2a,stroke:#555,stroke-width:1,color:#aaa

    %% ── External Data Sources ───────────────────────────────────────
    subgraph External["External Data Sources"]
        YF[(yfinance)]:::external
        MT5_[(MetaTrader 5)]:::external
        FRED[(FRED / Macro)]:::external
        COT[(COT Reports)]:::external
    end

    %% ── Data Layer ──────────────────────────────────────────────────
    subgraph Data["Data Layer"]
        direction TB
        CD[Config Domains<br/>configs/domains/]:::data
        PCR[PaperConfigRegistry]:::data
        SS[StateStore<br/>SQLite + JSON]:::data
        WAL[WAL Journal<br/>paper_trading/replay/wal.py]:::data
        EC[ExecutionContext]:::data
    end

    %% ── Feature Pipeline ────────────────────────────────────────────
    subgraph Features["Feature Engineering"]
        direction TB
        DF[DataFetch<br/>MT5 / yfinance]:::feature
        CB[CircuitBreaker<br/>_DataFetchCircuitBreaker]:::feature
        FE[Feature Builders<br/>regime, event, alpha, rates,<br/>positioning, macro, cot]:::feature
        LC[Liquidity Classifier]:::feature
        MC[Macro Narrative]:::feature
        RC[Regime Classifier]:::feature
        AC[Archetype Classifier]:::feature
    end

    %% ── Core Engine ─────────────────────────────────────────────────
    subgraph Engine["Paper Trading Engine"]
        direction TB
        PTE{{PaperTradingEngine<br/>paper_trading/engine.py}}:::core

        subgraph Orchestrator["EngineOrchestrator — 5-Phase Cycle"]
            direction LR
            PRE[Pre-Phase<br/>PEK state +<br/>macro prefetch]:::core
            P1[Phase 1a<br/>Signal Gen<br/>(parallel actors)]:::core
            P1B[Phase 1b<br/>PEK Admission]:::risk
            P2[Phase 2<br/>Validity]:::core
            P3[Phase 3<br/>Portfolio Health<br/>• Drawdown breaker<br/>• Halt ratio breaker<br/>• Vol spike breaker<br/>• VaR/CVaR<br/>• Recovery scheduler<br/>• MT5 orphan reconciliation]:::risk
            P4[Phase 4<br/>Persist + WAL]:::core
            PRE --> P1 --> P1B --> P2 --> P3 --> P4
        end

        subgraph Actors["Per-Asset Actors (ThreadPoolExecutor)"]
            direction TB
            AA1[AssetActor EURUSD]:::service
            AA2[AssetActor GBPUSD]:::service
            AA3[AssetActor CADCHF]:::service
            AAmore[... 21 total]:::service
        end

        subgraph AssetLogic["AssetEngine (per asset)"]
            direction TB
            IP[Inference Pipeline<br/>XGBoost model]:::service
            TP[Training Pipeline]:::service
            PM[Position Manager]:::service
            AE[Adaptive Exit Engine<br/>4-stage retracement trail]:::service
            SLTP[Dynamic SL/TP Engine]:::service
            GV[Governance<br/>• Narrative scalars<br/>• Liquidity scalars<br/>• Regime conviction gate<br/>• Spread gate<br/>• Cooldown logic]:::service
            MG[Metrics + Edge Health]:::service
            AT[Attribution Collector]:::service
        end
    end

    %% ── PEK / Risk ──────────────────────────────────────────────────
    subgraph Pek["Portfolio Execution Kernel"]
        direction TB
        PEK[PortfolioAdmissionController<br/>paper_trading/pek/]:::risk
        RB[RiskBudget]:::risk
        PS[PortfolioStateSnapshot]:::risk
        PSB[PerformanceStateBuilder]:::risk
        RE[RiskEngineV2<br/>adaptive budget]:::risk
    end

    %% ── Services ────────────────────────────────────────────────────
    subgraph Services["Engine Services"]
        direction TB
        ESS[EngineStateService<br/>state.json builder]:::service
        ERS[EngineRebalanceService]:::service
        ERCS[EngineRecoveryService]:::service
        ENS[EngineNarrativeService]:::service
        BS[BrokerFactory<br/>MT5 / Paper]:::service
    end

    %% ── Dashboard ───────────────────────────────────────────────────
    subgraph Dashboard["React SPA Dashboard"]
        direction TB
        API[state.json endpoint<br/>paper_trading/serve.py]:::frontend
        ADM[AdmissionPanel<br/>+ BudgetGauge]:::frontend
        PEKP[PEK Scalar Panel]:::frontend
        EQ[Equity Chart]:::frontend
        POS[Position Concentration]:::frontend
        HEALTH[Health Scores]:::frontend
        SIGNAL[Signals Table]:::frontend
        TRADE[Trade Feed]:::frontend
        CORR[Risk Budget Chart]:::frontend
        CORR2[Performance Velocity Chart]:::frontend
    end

    %% ── Data Flow Connections ───────────────────────────────────────

    %% Config
    CD --> PCR --> EC
    PCR --> PTE

    %% Data Sources → Features
    YF --> DF
    MT5_ --> DF
    FRED --> MC
    COT --> FE
    DF --> FE
    CB -.->|monitors| DF
    FE --> RC
    FE --> LC
    FE --> AC

    %% Features → Assets
    RC --> IP
    LC --> GV
    MC --> GV
    AC --> IP
    FE --> IP
    DF --> IP

    %% Engine → Orchestrator
    PTE --> Orchestrator
    Orchestrator -->|asset signals| PTE

    %% Orchestrator → Actors
    P1 -->|submit parallel| Actors
    Actors -->|AssetResult| P1

    %% Actors → AssetLogic
    AA1 -.->|wraps| AssetLogic
    AA2 -.->|wraps| AssetLogic
    AAmore -.->|wraps| AssetLogic

    %% PEK integration
    PRE --> PSB
    PRE --> PS
    PS --> RE
    PSB --> RE
    RE --> RB
    PS --> PEK
    RB --> PEK
    P1 -->|intents| P1B
    PEK -->|admission| P1B

    %% Services
    PTE --> BS
    PTE --> Services
    ESS -->|save_state| SS
    Orchestrator -->|WAL events| WAL
    WAL --> ESS

    %% State flow
    SS -->|restore on restart| PTE
    ESS -->|state.json| API

    %% Dashboard
    API --> ADM
    API --> PEKP
    API --> EQ
    API --> POS
    API --> HEALTH
    API --> SIGNAL
    API --> TRADE
    API --> CORR
    API --> CORR2

    %% ── Data Flow Annotations ───────────────────────────────────────
    linkStyle 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30 stroke-width:1.5,opacity:0.7
```

## Execution Cycle (60s Loop)

```
┌──────────────────────────────────────────────────────────────────┐
│                    60-Second Orchestrator Cycle                   │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  PRE ─► 1a ─► 1b ─► 2 ─► 3 ─► 4                                │
│   │      │      │     │    │    │                                 │
│   │      │      │     │    │    └─ Persist buffers + WAL commit  │
│   │      │      │     │    │                                      │
│   │      │      │     │    └── 3a. Drawdown circuit breaker      │
│   │      │      │     │        3b. Halt ratio check              │
│   │      │      │     │        3c. Vol spike + consec. losses    │
│   │      │      │     │        3d. Leverage anomaly (obs.)       │
│   │      │      │     │        3e. Position concentration        │
│   │      │      │     │        3f. Cross-asset correlation       │
│   │      │      │     │        3g. MT5 orphan reconciliation     │
│   │      │      │     │        3h. HealthMonitor + VaR/CVaR      │
│   │      │      │     │            + RecoveryScheduler           │
│   │      │      │     │                                           │
│   │      │      │     └── Validity state machine updates         │
│   │      │      │          (all actors in parallel)              │
│   │      │      │                                                 │
│   │      │      └── PEK admission review (budget cap)            │
│   │      │                                                        │
│   │      └── Parallel actor execution (ThreadPoolExecutor)       │
│   │          Each actor: refresh_price → update_pnl → signal      │
│   │                                                                │
│   └── PEK state snapshot + macro data pre-fetch                   │
│       Circuit breaker: 3 consecutive MT5 failures → skip MT5     │
└──────────────────────────────────────────────────────────────────┘
```

## Layer Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Frontend (React SPA)                                    │
│  paper_trading/dashboard/                                │
├──────────────────────────────────────────────────────────┤
│  API / Flask Server                                      │
│  paper_trading/serve.py → state.json, health, trades     │
├──────────────────────────────────────────────────────────┤
│  Engine Orchestrator                                      │
│  • PaperTradingEngine (coordinator)                      │
│  • EngineOrchestrator (5-phase cycle loop)               │
│  • 21 AssetActor instances (ThreadPoolExecutor)          │
│  • AssetEngine (per-asset: inference, positions, exits)  │
├──────────────────────────────────────────────────────────┤
│  Risk & Governance                                       │
│  • PEK: admission, budget, performance state             │
│  • Drawdown controls, halt state machine                 │
│  • Governance layers (17 core + 3 adaptive budget)       │
│  • Validity state machine (GREEN/DEGRADED/HALTED)        │
│  • Position sizing chain (multiplicative, 8 steps)       │
├──────────────────────────────────────────────────────────┤
│  Features & Labels                                       │
│  • Data fetch (MT5 / yfinance with circuit breaker)      │
│  • Feature builders (cross-sectional, regime, event,     │
│    alpha, rates, positioning, macro, COT, liquidity)     │
│  • Triple-barrier labeling + meta-labeling               │
├──────────────────────────────────────────────────────────┤
│  Configuration & Data Persistence                        │
│  • configs/domains/ (YAML domain tree)                   │
│  • PaperConfigRegistry → EngineConfig                    │
│  • StateStore (SQLite + JSON snapshots)                  │
│  • WAL journal (append-only event log)                   │
├──────────────────────────────────────────────────────────┤
│  External Integrations                                   │
│  • MetaTrader 5 (Wine-hosted, TCP bridge, port 9879)     │
│  • yfinance (fallback data source)                       │
│  • HashiCorp Vault (optional secrets)                    │
└──────────────────────────────────────────────────────────┘
```

## Key Metrics

| Metric | Value |
|--------|-------|
| Assets | 21 (FX, commodities, indices, BTCUSD) |
| Cycle frequency | 60 seconds |
| Actor pool | ThreadPoolExecutor (max 8 workers) |
| MT5 bridge | TCP frame protocol, port 9879, 4-pool circuit breaker |
| Model | Per-asset XGBoost (22 models) |
| Governance | 17 core layers + 3 adaptive budget layers |
| Position sizing | 8-step multiplicative chain (SizingChain) |
| Labels | 3-class (BUY/SELL/FLAT) with meta-labeling |
| Exit engine | 4-stage retracement trailing (adaptive) |
| SELL_ONLY | 6 CHF/JPY pairs (permanent) |
| Dashboard | React + TypeScript + Zod schemas |
