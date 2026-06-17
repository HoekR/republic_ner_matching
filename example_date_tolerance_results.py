#!/usr/bin/env python3
"""
Preview: Example output from date tolerance testing.

This shows what kind of results and insights you'd get from running
align_resolutions_sample.py on the 500-sample batch.
"""

import json

# Example output from date tolerance test
sample_results = {
    "test_parameters": {
        "sample_size": 500,
        "enriched_resolutions": 19134,
        "flat_resolutions": 692156,
        "date_windows_tested": [0, 1, 3, 7],
        "entity_types": ["places", "persons", "organizations"]
    },
    
    "date_tolerance_results": {
        "window_0_days_exact": {
            "attempts": 412,
            "matches": 127,
            "match_rate_percent": 30.8,
            "avg_date_diff": 2.3,
            "max_date_diff": 14,
            "distribution": {
                "0_days": 127,
                "1-2_days": 156,
                "3-7_days": 89,
                "8+_days": 40
            }
        },
        
        "window_1_day": {
            "attempts": 412,
            "matches": 283,
            "match_rate_percent": 68.7,
            "avg_date_diff": 0.8,
            "max_date_diff": 14,
            "interpretation": "±1 day catches 68.7% of matches"
        },
        
        "window_3_days": {
            "attempts": 412,
            "matches": 372,
            "match_rate_percent": 90.3,
            "avg_date_diff": 1.5,
            "max_date_diff": 14,
            "interpretation": "±3 days catches 90.3% of matches"
        },
        
        "window_7_days": {
            "attempts": 412,
            "matches": 403,
            "match_rate_percent": 97.8,
            "avg_date_diff": 2.1,
            "max_date_diff": 14,
            "interpretation": "±7 days catches 97.8% of matches (most outliers at ~7 days)"
        }
    },
    
    "analysis": {
        "recommendation": "Use ±3 days as tolerance",
        "rationale": [
            "Captures 90.3% of entity-matched resolutions",
            "Avoids extreme outliers (few matches beyond 3 days)",
            "Balances coverage vs. false positives",
            "Historical dating in 1626-1630 often has ±1-2 day variance"
        ],
        
        "outliers_observed": [
            {
                "case": 1,
                "enriched_date": "1627-03-15",
                "best_match_date": "1627-03-08",
                "date_diff": 7,
                "entity_overlap": {
                    "places": "Amsterdam, Rotterdam",
                    "persons": "Cornelis van Puyck"
                },
                "confidence": 0.72,
                "note": "Likely dating error in enriched metadata (week earlier)"
            },
            {
                "case": 2,
                "enriched_date": "1628-07-22",
                "best_match_date": "1628-07-30",
                "date_diff": 8,
                "entity_overlap": {
                    "places": "Den Briel",
                    "persons": "Wilhelm van Nassau"
                },
                "confidence": 0.65,
                "note": "Possible week-long gap in resolution numbering/dating"
            }
        ],
        
        "next_steps": [
            "Run full alignment with ±3 day window",
            "Inspect outliers for systematic dating patterns",
            "Check if certain resolution sequences have consistent gaps",
            "Consider entity confidence thresholds (current: 0.1 minimum)"
        ]
    }
}

if __name__ == '__main__':
    print("=" * 70)
    print("EXPECTED DATE TOLERANCE TEST RESULTS")
    print("=" * 70)
    print()
    
    print("Input Parameters:")
    for key, value in sample_results["test_parameters"].items():
        print(f"  {key}: {value}")
    print()
    
    print("Date Tolerance Test Results:")
    print("-" * 70)
    
    results = sample_results["date_tolerance_results"]
    
    print("\n[Window = 0 days (exact match only)]")
    r = results["window_0_days_exact"]
    print(f"  Attempts: {r['attempts']}")
    print(f"  Matches: {r['matches']} ({r['match_rate_percent']:.1f}%)")
    print(f"  Avg date diff: {r['avg_date_diff']:.1f} days")
    print(f"  Max date diff: {r['max_date_diff']} days")
    print(f"  Distribution: {json.dumps(r['distribution'], indent=4)}")
    
    print("\n[Window = ±1 day]")
    r = results["window_1_day"]
    print(f"  Attempts: {r['attempts']}")
    print(f"  Matches: {r['matches']} ({r['match_rate_percent']:.1f}%)")
    print(f"  → {r['interpretation']}")
    
    print("\n[Window = ±3 days]")
    r = results["window_3_days"]
    print(f"  Attempts: {r['attempts']}")
    print(f"  Matches: {r['matches']} ({r['match_rate_percent']:.1f}%)")
    print(f"  → {r['interpretation']}")
    
    print("\n[Window = ±7 days]")
    r = results["window_7_days"]
    print(f"  Attempts: {r['attempts']}")
    print(f"  Matches: {r['matches']} ({r['match_rate_percent']:.1f}%)")
    print(f"  → {r['interpretation']}")
    
    print("\n" + "-" * 70)
    print("ANALYSIS & RECOMMENDATION")
    print("-" * 70)
    print(f"\nRecommendation: {sample_results['analysis']['recommendation']}")
    print(f"\nRationale:")
    for i, point in enumerate(sample_results['analysis']['rationale'], 1):
        print(f"  {i}. {point}")
    
    print(f"\nOutlier Examples (date mismatches beyond ±3 days):")
    for case in sample_results['analysis']['outliers_observed']:
        print(f"\n  Case {case['case']}:")
        print(f"    Enriched date: {case['enriched_date']}")
        print(f"    Best match date: {case['best_match_date']}")
        print(f"    Date difference: {case['date_diff']} days")
        print(f"    Entities matched: {case['entity_overlap']}")
        print(f"    Confidence: {case['confidence']}")
        print(f"    Note: {case['note']}")
    
    print(f"\nNext Steps:")
    for i, step in enumerate(sample_results['analysis']['next_steps'], 1):
        print(f"  {i}. {step}")
    
    print("\n" + "=" * 70)
