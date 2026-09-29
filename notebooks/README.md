# Optional exploration

All authoritative processing is executable package code, not notebook state.

For exploration, run `uv run gridpulse features` and load `runtime/features.parquet` in a notebook.
Keep `target_timestamp` when inspecting splits. Model feature importance, chronological boundaries,
weekly-baseline metrics and the feature contract are in each MLflow run's `manifest.json`.
Do not randomly split the exported feature table or use the target column as an input feature.
