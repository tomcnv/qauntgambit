**Scope Freeze Gate**
- [ ] This PR contains no new strategy logic, no tuning, no performance claims unless Phase 1–3 are merged and CI‑passing.

**Phase Target**
- [ ] Phase 0
- [ ] Phase 1
- [ ] Phase 2
- [ ] Phase 3
- [ ] Phase 4

**Time Semantics Compliance**
- [ ] All new/modified events include `ts_recv_us`, optional `ts_exchange_s`, and `ts_canon_us` (canonical µs).
- [ ] No `time.time()`/`datetime.now()`/`Timestamp.now()` in snapshot/feature/window code paths.

**Tests**
- [ ] CI green (unit tests required).
- [ ] Added/updated contract tests as applicable.

**Summary**
Describe the change and why it is safe within the current phase.
