from scripts.evaluate_s4_paragraph_axis import transition_indices


def test_transition_indices_keeps_cut_and_start_boundaries():
    day = {
        "boundaries": [
            {"kind": "cut", "paragraph_stream_index": 1},
            {"kind": "end_of_last_resolution", "paragraph_stream_index": 2},
            {"kind": "start", "paragraph_stream_index": 3},
        ]
    }

    assert transition_indices(day) == [1, 3]