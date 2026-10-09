"""
Visualize extraction.json metric time-series as interactive Plotly charts.

Takes the same extraction.json that `src/rightsizing/rightsize.py` consumes
and produces a standalone `visualization.html` with one chart per metric,
overlaying every node as a separate line so a hot primary is visually
distinct from its secondaries at a glance.
"""
