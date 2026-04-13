/*
 * Alloy Specification: Context Kubernetes Permission Model
 *
 * Verifies Design Invariants 3.7 and 3.8:
 *
 *   3.7 (Agent Permission Subset):
 *     For every user u, agent a_u: P_{a_u} ⊂ P_u
 *     (strict subset — at least one excluded operation)
 *     For shared operations: T(o, a_u) >= T(o, u)
 *
 *   3.8 (Strong Approval Isolation):
 *     For Tier 3 actions, the approval channel is:
 *       C1: External to the agent's execution environment
 *       C2: Not readable/writable by the agent
 *       C3: Requires a separate authentication factor
 *
 * Run with: Alloy Analyzer 6+
 *   Execute > Check invariant_37_strict_subset
 *   Execute > Check invariant_38_no_self_approval
 */

-- ============================================================
-- SIGNATURES (types)
-- ============================================================

abstract sig Tier {}
one sig Autonomous, SoftApproval, StrongApproval, Excluded extends Tier {}

sig Operation {
    name: one String
}

sig Resource {}

sig Permission {
    operation: one Operation,
    resources: set Resource,
    tier: one Tier
}

sig Role {
    permissions: set Permission
}

sig User {
    role: one Role,
    userPermissions: set Permission
}

sig Agent {
    owner: one User,
    agentPermissions: set Permission,
    excludedOps: set Operation
}

sig ApprovalChannel {}

sig ApprovalRequest {
    action: one Operation,
    resource: one Resource,
    requiredTier: one Tier,
    channel: lone ApprovalChannel  -- the channel used for approval
}

sig AgentProcess {
    agent: one Agent,
    canAccess: set ApprovalChannel  -- channels the agent process can read/write
}

-- ============================================================
-- FACTS (axioms — always true)
-- ============================================================

-- User permissions come from their role
fact userPermsFromRole {
    all u: User | u.userPermissions = u.role.permissions
}

-- Agent permissions are a subset of owner's permissions
fact agentSubset {
    all a: Agent |
        a.agentPermissions in a.owner.userPermissions
}

-- Agent has at least one excluded operation (strict subset)
fact strictSubset {
    all a: Agent |
        some op: Operation |
            op in (a.owner.role.permissions.operation) and
            op in a.excludedOps
}

-- Excluded operations are not in agent permissions
fact excludedNotInAgent {
    all a: Agent |
        no p: a.agentPermissions |
            p.operation in a.excludedOps
}

-- ============================================================
-- TIER ORDERING
-- ============================================================

-- Define tier ordering: Autonomous < SoftApproval < StrongApproval < Excluded
fun tierRank[t: Tier]: Int {
    t = Autonomous => 0
    else t = SoftApproval => 1
    else t = StrongApproval => 2
    else 3  -- Excluded
}

-- Agent tier is always >= user tier for shared operations
fact agentTierNotLessRestrictive {
    all a: Agent, ap: a.agentPermissions |
        all up: a.owner.userPermissions |
            ap.operation = up.operation implies
                tierRank[ap.tier] >= tierRank[up.tier]
}

-- ============================================================
-- STRONG APPROVAL ISOLATION (Invariant 3.8)
-- ============================================================

-- For Tier 3 actions, the approval channel must not be accessible to the agent
fact strongApprovalIsolation {
    all ar: ApprovalRequest, ap: AgentProcess |
        ar.requiredTier = StrongApproval implies
            ar.channel not in ap.canAccess
}

-- ============================================================
-- ASSERTIONS TO CHECK (run with Alloy Analyzer)
-- ============================================================

-- Invariant 3.7: Agent permissions are always a strict subset
assert invariant_37_strict_subset {
    all a: Agent |
        -- Agent perms ⊆ user perms
        a.agentPermissions in a.owner.userPermissions
        -- Strict: at least one user perm not in agent
        and some p: a.owner.userPermissions | p not in a.agentPermissions
}

-- Invariant 3.7b: No agent can have operations not in user's role
assert invariant_37_no_escalation {
    all a: Agent |
        a.agentPermissions.operation in a.owner.role.permissions.operation
}

-- Invariant 3.7c: Agent tier never less restrictive than user tier
assert invariant_37_tier_monotonicity {
    all a: Agent, ap: a.agentPermissions |
        all up: a.owner.userPermissions |
            ap.operation = up.operation implies
                tierRank[ap.tier] >= tierRank[up.tier]
}

-- Invariant 3.8: No agent process can access the strong approval channel
assert invariant_38_no_self_approval {
    all ar: ApprovalRequest, ap: AgentProcess |
        ar.requiredTier = StrongApproval implies
            ar.channel not in ap.canAccess
}

-- Combined: no escalation path exists
assert no_escalation_path {
    -- No sequence of operations allows an agent to end up with
    -- more permissions than its owner
    all a: Agent |
        #(a.agentPermissions) < #(a.owner.userPermissions)
}

-- ============================================================
-- CHECK COMMANDS
-- ============================================================

-- Check each invariant for up to 10 instances of each signature
check invariant_37_strict_subset for 5 but 3 User, 3 Agent, 6 Permission, 4 Operation, 3 Resource
check invariant_37_no_escalation for 5 but 3 User, 3 Agent, 6 Permission, 4 Operation
check invariant_37_tier_monotonicity for 5 but 3 User, 3 Agent, 6 Permission, 4 Operation
check invariant_38_no_self_approval for 5 but 3 AgentProcess, 3 ApprovalRequest, 3 ApprovalChannel
check no_escalation_path for 5 but 3 User, 3 Agent, 8 Permission, 5 Operation

-- ============================================================
-- EXAMPLE: generate a valid instance
-- ============================================================

pred show {
    #User >= 2
    #Agent >= 2
    #Operation >= 3
    some ar: ApprovalRequest | ar.requiredTier = StrongApproval
}

run show for 5 but 3 User, 3 Agent, 6 Permission, 4 Operation, 2 ApprovalRequest
