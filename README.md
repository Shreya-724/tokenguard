# tokenguard
A token-aware, Redis-backed rate limiter for Django, built for LLM APIs.

**Goal:** limit requests by *tokens consumed*, not just request count, with
atomic correctness under concurrency and a live dashboard.

**Status:** Week 1 of 8, in-memory core algorithm.