# RepoOperator Web Manual QA

Use this checklist after runtime or chat-stream changes.

1. Open a repository chat.
2. Send `이 레포가 뭐 하는 프로젝트인지 알아내줘.`
3. Confirm progress appears while the final answer is still buffered.
4. Navigate away before completion.
5. Navigate back.
6. Confirm the same thread is visible.
7. Confirm progress or the final answer rehydrates from backend events.
8. Confirm there is no duplicate assistant message.
9. Confirm repeated progress updates merge into stable cards.
10. Send `README.md랑 가장 중요한 entrypoint 파일 하나만 읽고, 실행 흐름을 설명해줘.`
11. Confirm the answer appears and the thread remains after navigation.
12. Send `지난 작업 이력 보여줘.`
13. Confirm read-only Git history/status output appears.
14. Send `지난 작업 이력 보여주고, 지금 변경사항 커밋해줘.`
15. Confirm commit execution is approval-gated and is not run automatically.

## Thread rehydration (from 2026 patch)

- Active-thread localStorage key is now **repo-scoped**: `repooperator-active-thread:{provider}:{path}`.
  Opening a different repo will start a fresh thread; switching back restores the prior thread for that repo.
  Legacy global key `repooperator-active-thread-id` is read as a one-time fallback and then removed.
- The rehydrate loop guard (using a ref) prevents repeated rehydration when `activeRunByThread` changes.
  Verify by: opening a thread, starting a run, navigating away mid-run, navigating back — confirm single rehydration, no loop.
- Progress cleanup after a run completes is **synchronous** (via `finalizeRunInUi`), replacing the old `setTimeout(100)` hack.
  Verify by: completing a run, immediately navigating away and back — confirm no stale progress cards.
