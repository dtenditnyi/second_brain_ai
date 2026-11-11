# STATUS

- Rounds 1–3: DONE (Round 3 on `feature/round3`, 825 passed).
- **Current: Round 4** (`feature/round4`). Method: `docs/audit/PROMPT_LEAN.md`. Goals: `docs/audit/round4/GOALS.md`.
- Done: acceptance tests; **part D (editor)**; **part E (providers incl. Claude, agent, agent UI)** — D/E xfail removed, fast suite green (530 passed).
- Next: part API (`core/api_v1/`, Link2Note contract — PROMPT_LEAN §8) → end of round (full run, one reviewer, docs, Round 5 GOALS + xfail tests).
- **Следующий шаг:** clone the Link2Note contract (PROMPT_LEAN §8.1) into `docs/link2note/`, read `test_api*` (test_round4.py ~760–971), implement `/api/v1/`.
