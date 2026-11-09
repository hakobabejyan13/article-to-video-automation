"""Exit codes, as defined in PLAN.md section 0."""

OK = 0            # success, or stopped cleanly at the review gate
CHECK_FAILED = 1  # checker or length failure
SETUP = 2         # missing setup or input (also: stage not built yet)
PROVIDER = 3      # provider unavailable after retries
