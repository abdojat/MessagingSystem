# Transaction Lock Ordering

Phase 7 defines this order for security-sensitive transactions that acquire
more than one blocking PostgreSQL lock class:

```text
User / UserSession quota or lifecycle row
  -> Channel
  -> ChannelMembership / ChannelInvite / Message / UserChannelState / Upload
  -> existing Outbox claim
  -> BrokerBindingState
  -> event-integrity advisory lock
```

Not every transaction needs every class. It must preserve the relative order
of the classes it does use. Newly inserted outbox rows are not existing-row
claims and cannot be waited on by another transaction before commit.

Rules:

- Channel topology and membership mutations lock `Channel` first.
- Multiple memberships, binding states, or advisory scopes are processed in
  stable UUID/scope order.
- Message/read-state writes take a shared or exclusive channel lock before
  message, membership, or seen-state row locks.
- Invite acceptance/revocation takes `Channel` before `ChannelInvite`.
- The worker claims one `Outbox` row per transaction, then at most one
  `BrokerBindingState` row. It does not retain a batch of binding locks.
- RabbitMQ projection status commits before broker retry/dead-letter audit is
  attempted. The diagnostic transaction takes only its event advisory lock.
- Event-integrity advisory locks are last in application transactions. A
  standalone system/security audit transaction may take only that lock.
- The Phase 11 Merkle checkpoint transaction uses a dedicated two-key advisory
  lock namespace (`audit_merkle_checkpoint_v1`). It takes no row lock on the
  whole event table and no per-scope event-integrity advisory lock. Checkpoint
  jobs serialize with each other only; ordinary event writers continue and
  events not visible to the checkpoint transaction remain pending for a later
  batch.
- Refresh rotation locks one `UserSession`; refresh-replay revocation commits
  before its separate best-effort system audit transaction.

PostgreSQL `40P01`/`40001` can still occur for unrelated workloads. Worker
outbox work is idempotent/at-least-once and a rolled-back claim remains eligible
for the next paced poll. Post-commit diagnostic event writes use a maximum of
three retries only for those two transaction errors. HTTP writes are not
blindly replayed because they may contain non-repeatable side effects.
