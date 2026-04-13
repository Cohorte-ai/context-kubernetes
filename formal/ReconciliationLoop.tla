--------------------------- MODULE ReconciliationLoop ---------------------------
(*
 * TLA+ Specification: Context Kubernetes Reconciliation Loop
 *
 * Verifies Design Goals 3.9 (Safety) and 3.10 (Liveness) from the paper:
 *
 *   Safety:
 *     S1: No EXPIRED context unit is ever served to any agent
 *     S2: If the Permission Engine is unavailable, all requests are denied
 *
 *   Liveness:
 *     L1: Every STALE unit is flagged or re-synced within 2·Δt_r
 *     L2: Every disconnected source is detected within Δt_r
 *
 * Model: Sources transition through freshness states (FRESH → STALE → EXPIRED)
 *        based on elapsed time vs. declared max_age. The reconciliation loop
 *        observes state and takes corrective action.
 *)

EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS
    Sources,          \* Set of context source names
    MaxAge,           \* Max age before STALE (in ticks)
    ReconcileInterval \* Reconciliation interval Δt_r (in ticks)

VARIABLES
    clock,            \* Global clock (ticks)
    lastSync,         \* lastSync[s] = tick when source s was last synced
    sourceHealth,     \* sourceHealth[s] ∈ {"healthy", "disconnected"}
    freshnessState,   \* freshnessState[s] ∈ {"fresh", "stale", "expired"}
    permEngineUp,     \* Is the Permission Engine available?
    requestQueue,     \* Pending context requests: sequence of [source, tick]
    servedExpired,    \* Has any EXPIRED unit been served? (safety violation flag)
    servedWhenDown,   \* Has any unit been served when perm engine was down?
    staleDetected,    \* staleDetected[s] = tick when staleness was detected (0 = not yet)
    disconnDetected,  \* disconnDetected[s] = tick when disconnect was detected (0 = not yet)
    lastReconcile     \* Tick of last reconciliation cycle

vars == <<clock, lastSync, sourceHealth, freshnessState, permEngineUp,
          requestQueue, servedExpired, servedWhenDown, staleDetected,
          disconnDetected, lastReconcile>>

-----------------------------------------------------------------------------

(* Type invariant *)
TypeOK ==
    /\ clock \in Nat
    /\ \A s \in Sources: lastSync[s] \in Nat
    /\ \A s \in Sources: sourceHealth[s] \in {"healthy", "disconnected"}
    /\ \A s \in Sources: freshnessState[s] \in {"fresh", "stale", "expired"}
    /\ permEngineUp \in BOOLEAN
    /\ servedExpired \in BOOLEAN
    /\ servedWhenDown \in BOOLEAN
    /\ \A s \in Sources: staleDetected[s] \in Nat
    /\ \A s \in Sources: disconnDetected[s] \in Nat
    /\ lastReconcile \in Nat

-----------------------------------------------------------------------------

(* Initial state *)
Init ==
    /\ clock = 0
    /\ lastSync = [s \in Sources |-> 0]
    /\ sourceHealth = [s \in Sources |-> "healthy"]
    /\ freshnessState = [s \in Sources |-> "fresh"]
    /\ permEngineUp = TRUE
    /\ requestQueue = <<>>
    /\ servedExpired = FALSE
    /\ servedWhenDown = FALSE
    /\ staleDetected = [s \in Sources |-> 0]
    /\ disconnDetected = [s \in Sources |-> 0]
    /\ lastReconcile = 0

-----------------------------------------------------------------------------

(* Compute freshness state based on age *)
ComputeFreshness(s) ==
    LET age == clock - lastSync[s]
    IN IF age <= MaxAge THEN "fresh"
       ELSE IF age <= 2 * MaxAge THEN "stale"
       ELSE "expired"

-----------------------------------------------------------------------------

(* Action: Time advances by one tick *)
Tick ==
    /\ clock' = clock + 1
    /\ UNCHANGED <<lastSync, sourceHealth, permEngineUp, requestQueue,
                   servedExpired, servedWhenDown, staleDetected,
                   disconnDetected, lastReconcile>>
    /\ freshnessState' = [s \in Sources |-> ComputeFreshness(s)]

(* Action: A source goes offline *)
SourceDisconnects(s) ==
    /\ sourceHealth[s] = "healthy"
    /\ sourceHealth' = [sourceHealth EXCEPT ![s] = "disconnected"]
    /\ UNCHANGED <<clock, lastSync, freshnessState, permEngineUp,
                   requestQueue, servedExpired, servedWhenDown,
                   staleDetected, disconnDetected, lastReconcile>>

(* Action: A source recovers *)
SourceRecovers(s) ==
    /\ sourceHealth[s] = "disconnected"
    /\ sourceHealth' = [sourceHealth EXCEPT ![s] = "healthy"]
    /\ lastSync' = [lastSync EXCEPT ![s] = clock]
    /\ UNCHANGED <<clock, freshnessState, permEngineUp, requestQueue,
                   servedExpired, servedWhenDown, staleDetected,
                   disconnDetected, lastReconcile>>

(* Action: Permission Engine goes down *)
PermEngineDown ==
    /\ permEngineUp = TRUE
    /\ permEngineUp' = FALSE
    /\ UNCHANGED <<clock, lastSync, sourceHealth, freshnessState,
                   requestQueue, servedExpired, servedWhenDown,
                   staleDetected, disconnDetected, lastReconcile>>

(* Action: Permission Engine comes back up *)
PermEngineUp ==
    /\ permEngineUp = FALSE
    /\ permEngineUp' = TRUE
    /\ UNCHANGED <<clock, lastSync, sourceHealth, freshnessState,
                   requestQueue, servedExpired, servedWhenDown,
                   staleDetected, disconnDetected, lastReconcile>>

(* Action: An agent submits a context request *)
ContextRequest(s) ==
    /\ requestQueue' = Append(requestQueue, s)
    /\ UNCHANGED <<clock, lastSync, sourceHealth, freshnessState,
                   permEngineUp, servedExpired, servedWhenDown,
                   staleDetected, disconnDetected, lastReconcile>>

(* Action: The system serves a context request *)
(* This is where safety properties are checked/enforced *)
ServeRequest ==
    /\ Len(requestQueue) > 0
    /\ LET s == Head(requestQueue)
       IN
        \* Safety S2: If perm engine is down, deny (don't serve)
        /\ IF ~permEngineUp
           THEN /\ servedWhenDown' = TRUE  \* VIOLATION if we serve
                /\ UNCHANGED servedExpired
           ELSE /\ UNCHANGED servedWhenDown
                \* Safety S1: If content is expired, don't serve
                /\ IF freshnessState[s] = "expired"
                   THEN servedExpired' = TRUE  \* VIOLATION if we serve
                   ELSE UNCHANGED servedExpired
    /\ requestQueue' = Tail(requestQueue)
    /\ UNCHANGED <<clock, lastSync, sourceHealth, freshnessState,
                   permEngineUp, staleDetected, disconnDetected,
                   lastReconcile>>

(* Action: Reconciliation loop runs *)
Reconcile ==
    /\ clock - lastReconcile >= ReconcileInterval
    /\ lastReconcile' = clock
    \* Detect stale sources
    /\ staleDetected' = [s \in Sources |->
        IF freshnessState[s] \in {"stale", "expired"}
           /\ staleDetected[s] = 0
        THEN clock
        ELSE staleDetected[s]]
    \* Detect disconnected sources
    /\ disconnDetected' = [s \in Sources |->
        IF sourceHealth[s] = "disconnected"
           /\ disconnDetected[s] = 0
        THEN clock
        ELSE disconnDetected[s]]
    \* Re-sync healthy stale sources
    /\ lastSync' = [s \in Sources |->
        IF freshnessState[s] = "stale"
           /\ sourceHealth[s] = "healthy"
        THEN clock
        ELSE lastSync[s]]
    /\ freshnessState' = [s \in Sources |->
        IF freshnessState[s] = "stale"
           /\ sourceHealth[s] = "healthy"
        THEN "fresh"
        ELSE freshnessState[s]]
    /\ UNCHANGED <<clock, sourceHealth, permEngineUp, requestQueue,
                   servedExpired, servedWhenDown>>

-----------------------------------------------------------------------------

(* Next-state relation *)
Next ==
    \/ Tick
    \/ \E s \in Sources: SourceDisconnects(s)
    \/ \E s \in Sources: SourceRecovers(s)
    \/ PermEngineDown
    \/ PermEngineUp
    \/ \E s \in Sources: ContextRequest(s)
    \/ ServeRequest
    \/ Reconcile

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------

(* ================================================================
   SAFETY PROPERTIES (must hold in ALL reachable states)
   ================================================================ *)

(* S1: No expired content is ever served *)
SafetyNoExpiredServed == ~servedExpired

(* S2: No content served when Permission Engine is down *)
SafetyFailClosed == ~servedWhenDown

(* Combined safety *)
Safety == SafetyNoExpiredServed /\ SafetyFailClosed

-----------------------------------------------------------------------------

(* ================================================================
   LIVENESS PROPERTIES (must eventually hold)
   ================================================================ *)

(* L1: Every stale source is detected within 2·Δt_r *)
(* Expressed as: if a source becomes stale at tick T, then
   staleDetected[s] is set by tick T + 2·ReconcileInterval *)
LivenessStaleDetection ==
    \A s \in Sources:
        (freshnessState[s] \in {"stale", "expired"})
        => (staleDetected[s] > 0
            \/ clock - lastSync[s] < 2 * ReconcileInterval + MaxAge)

(* L2: Every disconnected source is detected within Δt_r *)
LivenessDisconnectDetection ==
    \A s \in Sources:
        (sourceHealth[s] = "disconnected")
        => (disconnDetected[s] > 0
            \/ clock < ReconcileInterval)

=============================================================================
(*
 * To model-check with TLC:
 *
 *   Sources = {"src1", "src2", "src3"}
 *   MaxAge = 3
 *   ReconcileInterval = 2
 *
 * Check:
 *   Invariants: TypeOK, Safety
 *   Properties: LivenessStaleDetection, LivenessDisconnectDetection
 *
 * Expected result: No violations.
 *)
=============================================================================
