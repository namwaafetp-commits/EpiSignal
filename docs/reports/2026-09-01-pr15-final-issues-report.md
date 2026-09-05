# PR #15 final review issues report

Date: 2026-09-01
Branch: `codex/next-iteration`
Verification implementation head before this report: `8255e465e24fd2d3c12b65aabf8ed4dc5632e9ea`

1. **Legacy triage authority removed.** Production metadata resolution now validates extraction only; legacy triage remains available for historical and audit compatibility but is not used for matching, event creation, metadata repair, or extraction reuse.

2. **Final metadata priority.** The resolver priority is validated extraction, then unresolved.

3. **AI repair reuse/re-extraction rule.** Repair reuses only a complete, currently valid extraction that supplies the required missing metadata. An absent, incomplete, or invalid extraction triggers re-extraction from the title and clean article content, even when legacy triage fields exist.

4. **Progressive extraction context sizes.** Attempt A uses the title and the first 7,000 clean article characters. One expansion may use the configured cap, defaulting to 12,000 characters.

5. **Expanded retry trigger.** Exactly one expansion is attempted only after an accepted extraction is missing disease or the primary event country/location, additional article content exists, and the configured cap permits expansion. Missing admin1 alone does not trigger it. The same schema and validator are used; request guards, cost accounting, and no-sampling/no-network behavior are preserved.

6. **Extraction retry tests.** Tests cover location recovered from later content, complete initial extraction without retry, short article without retry, and request-guard prevention of expansion. Retry counts and accumulated request costs are recorded.

7. **Flash-brief UI rendering changes.** `/events/[publicId]` renders the latest structured summary using `trajectory`, `snapshot`, `key_driver`, `response`, and `risk`, with visible Snapshot, Key Driver, Response, and Public/Global Risk sections. Historical summaries without structured fields fall back to the legacy summary text.

8. **Human-readable location behavior.** Summary locations use local validated gazetteer names: admin1 plus country, country only, or `Unresolved location`. Stored matching identifiers are unchanged and no runtime network lookup was added.

9. **Backend test count.** `corepack pnpm verify`: 1,283 backend tests passed, with 2 existing warnings.

10. **Web test count.** `corepack pnpm verify`: 107 web tests passed across 14 test files.

11. **Pipeline-order gate.** `corepack pnpm test:pipeline`: 18 tests passed.

12. **Lint/typecheck/contracts/build.** `corepack pnpm verify` passed formatting, lint, mypy (`134` source files), TypeScript, web tests, backend tests, contract generation with no diff, and the production Next build.

13. **PR mergeability.** Current `origin/main` was merged into this branch with no conflicts. Final GitHub confirmation reports PR #15 as `MERGEABLE` and `OPEN`, with base `main` and head `codex/next-iteration`; the local worktree and pushed branch are clean and synchronized.

14. **Final PR head SHA.** The final SHA is reported in the completion handoff after the report commit and push.

15. **Production unchanged.** No deployment, production data change, or PR merge was performed.

16. **Repair not executed.** No production AI metadata repair was run.

17. **Scheduler unchanged.** The scheduler was not enabled, changed, or executed.
