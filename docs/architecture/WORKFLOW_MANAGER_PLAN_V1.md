# PDF Unlocker — Workflow Manager and Processing Core Plan

**Branch:** `feature/workflow-manager`
**Starting point:** merged `develop`
**Status:** Architecture plan — implementation not yet started

## 1. Objective

Build a reliable, modular PDF processing pipeline and a Workflow Manager
that coordinates the complete lifecycle of discovered PDF files.

The Workflow Manager is the orchestration layer. It coordinates independent
modules and controls their execution order. It must not duplicate the
business logic owned by those modules.

The implementation must preserve existing project functionality, profile
data, rule data, database records and user files.

## 2. Recommended module development order

### 2.1 Scanner

Responsibilities:
- Discover PDFs recursively from configured scan locations.
- Calculate SHA-256 hashes for stable file identity.
- Detect duplicate content.
- Exclude application storage and output directories from scanning.
- Avoid following symlinks.
- Register discovered files without modifying their source files.

### 2.2 Inbox Manager

Responsibilities:
- Validate incoming PDF files.
- Prepare discovered files for processing.
- Assign stable application-level file records.
- Track inbox state and processing eligibility.
- Coordinate safe inbox cleanup after successful handoff.

### 2.3 Archive Manager

Responsibilities:
- Maintain the immutable Original archive.
- Manage verified placement into result categories.
- Prevent accidental overwrites and duplicate archive entries.
- Preserve source files and support recovery after interrupted operations.

### 2.4 Unlock Engine

Responsibilities:
- Execute the selected profile and its approved rules.
- Process PDF files using the configured unlocking adapters.
- Verify generated output before reporting success.
- Return structured outcomes and error information.

### 2.5 Unlocker Manager

Responsibilities:
- Coordinate profile and rule execution for individual PDFs.
- Manage attempts and execution order.
- Handle successful, locked, corrupted, unsupported and failed outcomes.
- Record rule attempts for learning and audit purposes.

### 2.6 Learning and Job Queue

Responsibilities:
- Record processing outcomes.
- Maintain batch and job state.
- Support rule ranking using approved learning policy.
- Prevent duplicate job assignment.
- Preserve completed history across profiles.

### 2.7 Recovery Manager

Responsibilities:
- Detect interrupted and incomplete jobs.
- Resume or safely retry eligible work.
- Prevent duplicate processing after restart.
- Reconcile database state with files on disk.

### 2.8 Workflow Manager

Responsibilities:
- Coordinate the complete processing lifecycle.
- Invoke modules in the correct order.
- Enforce state transitions and processing safeguards.
- Coordinate normal, force, retry and recovery operations.
- Record workflow progress and failures.
- Avoid implementing scanner, archive or unlocking logic itself.

## 3. Target processing workflow

```mermaid
flowchart TD
    A[PDF Sources] --> B[Scanner]
    B --> C[Hash and Duplicate Detection]
    C --> D[Immutable Original Archive]
    D --> E[Inbox Manager]
    E --> F[Job Queue]
    F --> G[Unlocker Manager]
    G --> H[Unlock Engine]
    H --> I[Result Verification]
    I --> J[Archive Manager]
    J --> K[Unlocked]
    J --> L[Locked]
    J --> M[Corrupted / Unsupported]
    J --> N[Duplicates]
    G --> O[Learning Records]
    F --> P[Recovery Manager]
    P --> F
    Q[Workflow Manager] -. Orchestrates .-> B
    Q -. Orchestrates .-> E
    Q -. Orchestrates .-> G
    Q -. Orchestrates .-> J
    Q -. Orchestrates .-> P
## 4. Architectural rules

1. SQLite remains the shared source of truth for application state.
2. Every PDF has a stable identity based on its SHA-256 hash.
3. Original PDFs are immutable.
4. A PDF must never be marked unlocked until output verification succeeds.
5. Failed and interrupted jobs must be recoverable.
6. A retry must not accidentally create duplicate processing records.
7. Every profile/rule attempt must be recorded for learning.
8. The Workflow Manager coordinates modules but does not replace their responsibilities.
9. File operations must be safe against partial writes, crashes and existing destinations.
10. Existing user data must never be overwritten or deleted during development or migration.

## 5. Development milestones

### Milestone 1 — Processing Core Audit
- Audit the merged develop branch.
- Inventory existing scanner, inbox, archive, unlocker, queue and recovery code.
- Identify complete, partial, missing and duplicated responsibilities.
- Inspect database schemas and existing tests.
- Record compatibility constraints before changing code.

### Milestone 2 — Scanner
- Verify recursive discovery.
- Verify hashing and duplicate detection.
- Verify excluded paths and symlink handling.
- Test unreadable files and interrupted scans.

### Milestone 3 — Inbox and Archive
- Define file lifecycle states.
- Verify safe handoff from scanner to inbox.
- Verify immutable original storage.
- Test duplicate and interrupted file operations.

### Milestone 4 — Unlocking
- Audit the existing qpdf adapter and rule execution.
- Verify profile ordering and result classification.
- Verify output integrity before publication.
- Test locked, corrupted and unsupported PDFs.

### Milestone 5 — Queue, Learning and Recovery
- Verify batch sequencing.
- Verify persistent job state.
- Verify learning records and ranking.
- Test restart and retry scenarios.

### Milestone 6 — Workflow Manager
- Integrate the real modules.
- Implement orchestration and state transitions.
- Test complete workflows and recovery.
- Verify that module boundaries remain clear.

## 6. Testing requirements

Each module must have isolated unit tests and integration tests.

The complete workflow must be tested for:
- Successful PDF processing.
- Duplicate PDFs.
- Locked PDFs.
- Corrupted and unsupported PDFs.
- Missing or inaccessible files.
- Interrupted processing.
- Application restart and recovery.
- Repeated scans.
- Multiple profiles.
- Multiple batches.
- Existing destination files.

All tests must use temporary isolated test directories and databases.
Tests must never depend on or modify the developer's live PDF library.

## 7. Immediate next action

Start with Milestone 1: audit the merged develop branch.

Do not begin replacing existing modules until their current implementation,
interfaces, database dependencies and tests have been inspected.

The first deliverable is a processing-core audit identifying what can be
reused, what requires repair and what is genuinely missing.
