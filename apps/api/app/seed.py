"""Seed tooling: interaction definitions + opportunity catalog. Idempotent."""
from .catalog import CATALOG_VERSION, INTERACTIONS
from .db import Base, SessionLocal, engine
from .figure_kb import seed_figures
from .models import InteractionDefinition
from .opportunities import seed_opportunities


def run() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        added = 0
        for d in INTERACTIONS:
            if not db.get(InteractionDefinition, d["id"]):
                db.add(InteractionDefinition(
                    id=d["id"], type=d["type"], chapters=d["chapters"],
                    targets=d.get("targets", []), cognitive_cost=d.get("cognitive_cost", 0.3),
                    practical_key=d.get("practical_key"), content=d["content"],
                ))
                added += 1
        opps = seed_opportunities(db)
        figs = seed_figures(db)
        from .quotes import seed as seed_quotes
        from .world.ingestion import seed_ontology, seed_baseline_signals
        from .world.signals import recompute_signals
        occs = seed_ontology(db)
        quotes_added = seed_quotes(db)
        seed_baseline_signals(db)
        recompute_signals(db)
        db.commit()
        print(f"seeded {added} interaction definitions, {opps} opportunities, "
              f"{figs} public figures, {occs} occupations, "
              f"{quotes_added} quotes pending review ({CATALOG_VERSION})")


if __name__ == "__main__":
    run()
