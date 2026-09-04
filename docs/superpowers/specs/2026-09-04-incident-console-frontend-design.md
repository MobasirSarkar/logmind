# LogMind — Service 5: Incident Console Frontend Design

**Date:** 2026-09-04  
**Author:** LogMind Team  
**Status:** Approved for Implementation  
**Scope:** Service 5 of LogMind Distributed Architecture  

---

## 1. Executive Summary

LogMind is an engineering incident investigation platform for distributed applications. Its user interface is purposefully designed as an **incident investigation console**, rather than a generic chatbot interface.

**Service 5: Incident Console Frontend** provides a fast, intuitive, and responsive single-page web application. It gives on-call engineers immediate situational awareness during high-severity outages through:
1. A **Chronological Correlated Timeline** that visually isolates the earliest abnormal trigger from downstream cascading errors.
2. An **Evidence-Backed AI Investigation Panel** featuring clickable evidence citations linking directly to raw logs, distributed traces, and operational runbooks.
3. A **High-Performance Log Explorer** supporting exact keyword filters, semantic concept search, and virtualized log streaming.
4. A **Developer Dead-Letter Queue (DLQ) Manager** for inspecting, debugging, and replaying failed log payloads.

The visual design adheres to a **professional enterprise aesthetic**: crisp typography, flat dark-mode surfaces, subtle borders, high contrast, and **zero gradient gimmicks**.

---

## 2. Technology Stack & Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                    React 19 + TypeScript                    │
│                                                             │
│  ┌───────────────────────┐       ┌───────────────────────┐  │
│  │     Zustand Store     │       │     TanStack Query    │  │
│  │ (Active Filters & UI) │       │ (Server State/Polling)│  │
│  └───────────┬───────────┘       └───────────┬───────────┘  │
│              └───────────────┬───────────────┘              │
│                              ▼                              │
│                 ┌─────────────────────────┐                 │
│                 │   View & Component Tree │                 │
│                 │ (Timeline, AI, Log, DLQ)│                 │
│                 └────────────┬────────────┘                 │
│                              ▼                              │
│                 ┌─────────────────────────┐                 │
│                 │ Virtualized Table Engine│                 │
│                 │   (@tanstack/virtual)   │                 │
│                 └────────────┬────────────┘                 │
└──────────────────────────────┼──────────────────────────────┘
                               │ REST / JSON (FastAPI)
                               ▼
              LogMind Backend Services (1, 3, 4)
```

### Core Libraries
* **Framework:** React 19 with TypeScript and Vite.
* **Styling:** Tailwind CSS with a customized enterprise palette (flat surfaces, subtle 1px borders, zero gradients).
* **Server State & Caching:** TanStack Query v5 (React Query) for automatic polling, optimistic updates, and cache invalidation.
* **Client State:** Zustand for active incident selection, time-range pickers, and search drawer states.
* **Large Dataset Rendering:** `@tanstack/react-virtual` for virtualized rendering of 10,000+ log rows without browser DOM exhaustion.
* **Icons:** Lucide React for consistent, crisp SVG icons.

---

## 3. Visual Foundation & Design System (Enterprise Clean Light Mode)

The UI avoids distracting aesthetic gradients, heavy shadows, or decorative icon clutter, focusing on maximum operational readability and information density:

* **Light Background Palette:**
  - Base canvas: `#ffffff`
  - Background subtle: `#f6f8fa`
  - Crisp borders: `#d0d7de`
  - Panel surface: `#ffffff`
  - Text primary: `#1f2328`
  - Text muted: `#656d76`
* **Typography:**
  - Interface text: Clean system font stack (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto`)
  - Telemetry & Identifiers: Monospace stack (`SFMono-Regular, Menlo, Consolas, monospace`) for timestamps, trace IDs, and error signatures.
* **Minimalist Semantic Badges & Accents:**
  - Critical / Root Cause: `#cf222e` (Muted red background: `#ffebe9`, border: `#ff8182`)
  - Warning / Cascading: `#9a6700` (Muted amber background: `#fff8c5`, border: `#d4a72c`)
  - Success / Verified: `#1a7f37` (Muted green background: `#dafbe1`, border: `#4ac26b`)
  - Accent / Links: `#0969da` (Muted blue background: `#ddf4ff`)
* **Iconography Policy:**
  - Strict minimalism: icons are omitted from generic labels and used solely where functionally essential (e.g. status indicator dots, search input indicator, topology direction arrows).
---

## 4. Core Views & Component Specifications

### 4.1 Incident Investigation Console (`/incidents/:id`)
The primary screen during active outages:
1. **Incident Header Banner:**
   - Severity badge (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`).
   - Incident status indicator (`DETECTED`, `INVESTIGATING`, `MITIGATED`, `RESOLVED`).
   - Human-readable title, elapsed incident duration, and list of affected services.
2. **Correlated Timeline Component:**
   - Chronological vertical timeline ordered from earliest to latest event.
   - Highlights the **Initial Trigger** with a distinctive red marker and service tag.
   - Downstream events display relative elapsed milliseconds (e.g. `+18ms`, `+24ms`), demonstrating how latency or errors cascaded.
   - Clicking an event opens the underlying log details drawer.
3. **AI Investigation Panel:**
   - Suspected root-cause statement and confidence score percentage.
   - **Clickable Evidence Cards:** Lists each cited Log ID, Trace ID, and Runbook section. Clicking an evidence item filters the log explorer or opens the referenced document.
   - **Action Checklist:** Numbered operational recommendations with checkboxes.
   - **Manual Action Bar:** "Acknowledge Incident" and "Re-run AI Analysis" buttons.

### 4.2 High-Performance Log Explorer (`/logs`)
1. **Search Bar & Mode Toggle:**
   - Unified input supporting keyword search and semantic vector queries.
   - Toggle: `Exact Filter (BM25)` vs `Semantic Concept (kNN)` vs `Hybrid (RRF)`.
2. **Filter Sidebar:**
   - Quick filters for Environment, Service name, Log Level (`ERROR`, `WARN`, `INFO`), and Trace ID.
   - Time-range selector (Last 15m, 1h, 6h, 24h, Custom).
3. **Virtualized Log Stream:**
   - Displays timestamp, service badge, level pill, trace ID, and message.
   - Row click expands inline JSON view showing parsed `context`, `http`, `error`, and `fingerprint` attributes.

### 4.3 Dead-Letter Queue (DLQ) Manager (`/dlq`)
1. **DLQ Records Table:**
   - Columns: Failed At, Tenant ID, Error Stage (`VALIDATION`, `INDEXING`), Retry Count (3/3), Error Message, Actions.
2. **Inspection Modal:**
   - Displays the unparsed original JSON payload side-by-side with the backend exception stack trace.
3. **Recovery Actions:**
   - **Replay Button:** Triggers `POST /api/v1/dlq/{id}/replay` to re-enqueue the record after schema fixes.
   - **Discard Button:** Triggers `DELETE /api/v1/dlq/{id}` with confirmation prompt.

---

## 5. TypeScript Domain Contracts

All frontend models mirror the backend Pydantic models:

```typescript
export type LogLevel = "DEBUG" | "INFO" | "WARN" | "ERROR" | "FATAL";
export type IncidentSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type IncidentStatus = "DETECTED" | "INVESTIGATING" | "MITIGATED" | "RESOLVED";
export type ErrorStage = "VALIDATION" | "SIGNATURE_EXTRACTION" | "EMBEDDING" | "INDEXING";
export type EvidenceType = "LOG" | "TRACE" | "RUNBOOK" | "HISTORICAL_INCIDENT";

export interface LogRecord<TMetadata = Record<string, unknown>> {
  id: string;
  timestamp: string;
  level: LogLevel;
  message: string;
  context: {
    tenant_id: string;
    service: string;
    environment: string;
  };
  trace?: {
    trace_id: string;
    span_id?: string;
    request_id?: string;
  };
  http?: {
    method: string;
    path: string;
    status_code: number;
  };
  error?: {
    error_type: string;
    error_message: string;
    error_signature?: string;
    stack_trace?: string;
  };
  fingerprint?: {
    content_hash: string;
    signature_hash?: string;
    hash_type: "sha256" | "md5";
    embedding?: number[];
  };
  metadata: TMetadata;
}

export interface IncidentEvent {
  event_id: string;
  incident_id: string;
  timestamp: string;
  service: string;
  event_type: string;
  error_signature?: string;
  trace_id?: string;
  log_id?: string;
  message: string;
}

export interface EvidenceItem {
  evidence_type: EvidenceType;
  reference_id: string;
  service?: string;
  timestamp?: string;
  excerpt: string;
}

export interface InvestigationReport {
  investigation_id: string;
  incident_id: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "DEGRADED_FALLBACK" | "FAILED";
  summary: string;
  suspected_root_cause: string;
  confidence_score: number;
  affected_services: string[];
  evidence: EvidenceItem[];
  recommended_actions: string[];
  is_fallback: boolean;
}

export interface DLQEntry<TPayload = Record<string, unknown>> {
  dlq_id: string;
  tenant_id: string;
  failed_at: string;
  retry_count: number;
  error_stage: ErrorStage;
  last_error: string;
  raw_payload: TPayload;
}
```

---

## 6. Test-Driven Development (TDD) Strategy

### 6.1 Test Suites Structure
```text
frontend/tests/
├── unit/
│   ├── components/
│   │   ├── IncidentHeader.test.tsx      # Severity badges & status labels
│   │   ├── CorrelatedTimeline.test.tsx  # Initial trigger marker & relative times
│   │   ├── EvidenceList.test.tsx        # Clickable evidence citations
│   │   └── DLQTable.test.tsx            # Inspect & replay button triggers
│   └── hooks/
│       ├── useLogSearch.test.ts         # Query params & mode toggles
│       └── useIncidentDetail.test.ts    # Polling & cache invalidation
└── integration/
    ├── IncidentInvestigationFlow.test.tsx # Full triage: review AI report -> filter log stream
    └── DLQRecoveryFlow.test.tsx           # Inspect corrupt log -> trigger replay -> toast feedback
```

### 6.2 TDD Implementation Sequence
1. **Phase 1: Design System & Shared Components (Unit TDD)**
   - Test: Write failing tests for Badge, Button, Panel, and Modal components.
   - Code: Implement components with strict Tailwind utility styling (no gradients).
2. **Phase 2: Timeline & Evidence Cards (Unit TDD)**
   - Test: Write failing tests asserting that the chronologically first event receives the root cause marker and evidence items invoke callback handlers.
   - Code: Implement `CorrelatedTimeline.tsx` and `EvidenceCard.tsx`.
3. **Phase 3: Virtualized Log Explorer (Unit TDD)**
   - Test: Write failing tests verifying search input mode switches (BM25 vs kNN) and virtualized row rendering.
   - Code: Implement `LogExplorer.tsx` with `@tanstack/react-virtual`.
4. **Phase 4: DLQ Management View (Integration TDD)**
   - Test: Write failing tests asserting table rendering, modal inspection, and replay API call with MSW (Mock Service Worker).
   - Code: Implement `DLQManager.tsx`.
5. **Phase 5: End-to-End Incident Detail Page (Integration TDD)**
   - Test: Assert end-to-end rendering of simulated incident `INC-8492` matching the approved preview.
   - Code: Implement `IncidentDetailPage.tsx`.

---

## 7. Definition of Done for Service 5

1. All Vitest and React Testing Library suites pass with 100% green status.
2. The user interface matches the approved design in `docs/preview/incident-console.html` with flat enterprise styling and zero gradients.
3. The correlated timeline renders incident events with distinct markers for the initial root cause vs downstream consequences.
4. AI investigation reports display verified evidence cards that link directly into the log explorer.
5. The Log Explorer virtualizes 1,000+ log lines smoothly without scroll jitter or frame drops.
6. The DLQ view allows developers to inspect failed payloads and trigger replay requests.
