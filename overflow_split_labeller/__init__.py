"""PARKED — overflow-split treatment UI.

Do not use until ``aligned_to_overflow_track_gold`` exists and has been
inspected (as-is → proposed_end). Cut char offsets are machine proposals
only; bake track gold first:

    uv run python -m sequence_graph.fingerprint_session_shift --bake-track-gold --write

See ``docs/steps/STEP_NEIGHBOURHOOD_SESSION_SHIFT.md`` Step 5–6.
"""