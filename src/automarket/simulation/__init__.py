"""Simulation package — optional historical listing snapshot generator.

This module is EXPLICITLY OPTIONAL and NOT part of the default ingestion path.
All simulated records are clearly marked with is_simulated=True and
observation_date to distinguish them from source data.

Limitations (documented):
- The source dataset is a static snapshot without publication timestamps.
- Simulated observation dates are NOT real listing publication dates.
- Simulated price changes are NOT based on actual market movements.
- A simulated disappearance does NOT mean the vehicle was sold.
- Outputs should never be interpreted as evidence about real market history.
"""
