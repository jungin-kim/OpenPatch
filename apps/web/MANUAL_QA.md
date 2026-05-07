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
