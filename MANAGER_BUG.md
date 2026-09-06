# 🐛 MANAGER INBOX — PM1 Bug Report

**Date:** 2026-09-07
**From:** PM1 (Project Manager 1, ToonPop)
**Severity:** 🔴 HIGH — blocks auto Telegram script delivery

## Bug: GitHub token expired (401 Bad credentials)

- `git push` to `main` works (commit `a1b9e55` live).
- REST `POST /actions/workflows/{file}/dispatches` returns **401** for
  trend / script / manager / analytics workflows.
- Effect: cron schedules still fire on time, but PM1 **cannot manually
  trigger** batch 1 / loop restart on demand. CEO got zero Telegram prompts.
- CEO impact: had to receive Batch 1 in chat (dies if PC off) instead of Telegram.

## Fix needed (Manager decides)
- **Option A:** CEO pastes a fresh fine-grained/classic token
  (`repo` + `workflow` scopes) → PM1 stores it, triggers dispatch.
- **Option B:** CEO taps Run workflow on phone (no token needed):
  1. `script-workflow.yml` → batch 1 to Telegram
  2. `bot-workflow.yml` → reload loop (done-reply + auto-next-batch)

## PM1 status while blocked
- All 8 workflows + 13 bot files on `main`, compile-verified.
- Batch loop code live, waiting for loop restart (cron ≤6h or manual run).
- Next auto-fire: trend 09:00 IST → script 09:30 IST → manager 11:00 IST.
