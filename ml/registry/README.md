# Model Registry

Database-backed (`model_registry` table). Artifacts live here (dev) or in
S3-compatible object storage (production, via env). States:

candidate → evaluated → shadow → canary → production → retired

Promotion is always explicit (`scripts/promote_model.py`). Shadow models log
`shadow_predictions` beside production output and never affect users.
