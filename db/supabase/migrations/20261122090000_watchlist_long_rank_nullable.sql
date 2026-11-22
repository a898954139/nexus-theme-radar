-- Moat gate (job/scripts/moat_screen.py, rule moat_v1): the long list is now a
-- subset of the short list. A name that passes the short rules but not the long
-- ones (TTM operating cash flow <= 0) keeps its short rank and has no long rank.
-- Additive and re-runnable. Until this runs, the hourly job detects NOT NULL and
-- keeps the long gate off (log: moat_long_gate_off), so order does not matter.
alter table radar.watchlist_item alter column long_rank drop not null;
