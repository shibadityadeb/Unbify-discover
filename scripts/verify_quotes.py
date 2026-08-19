#!/usr/bin/env python3
"""Human verification gate for the Quote Intelligence Library.

Quotes are seeded as `review_needed` and are invisible to users until someone
checks the wording against the cited primary source and marks them verified.
This exists because a misattributed quote is worse than no quote — and because
no model, including the one that wrote the seed file, should be trusted to
recall wording accurately.

    python3 scripts/verify_quotes.py list                 # what is pending
    python3 scripts/verify_quotes.py show   <quote_id>
    python3 scripts/verify_quotes.py verify <quote_id> [<quote_id> ...]
    python3 scripts/verify_quotes.py reject <quote_id> [<quote_id> ...]
    python3 scripts/verify_quotes.py status
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.db import SessionLocal                     # noqa: E402
from app.models import QuotePerson, QuoteRecord, QuoteSource   # noqa: E402


def _line(db, q):
    person = db.get(QuotePerson, q.person_id)
    source = db.get(QuoteSource, q.source_id)
    return (f"[{q.verification_status:14}] {q.id}\n"
            f"    \"{q.quote_text}\"\n"
            f"    — {person.name if person else '?'} ({person.field if person else '?'})\n"
            f"    source: {source.title if source else '?'}"
            f"{', ' + source.published_at if source and source.published_at else ''}"
            f"{' — ' + source.url if source and source.url else ''}\n"
            f"    themes: {', '.join(q.themes or [])}")


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    ids = sys.argv[2:]
    with SessionLocal() as db:
        if command == "status":
            rows = db.query(QuoteRecord).all()
            counts: dict[str, int] = {}
            for r in rows:
                counts[r.verification_status] = counts.get(r.verification_status, 0) + 1
            print(f"{len(rows)} quotes: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
            if counts.get("verified", 0) == 0:
                print("\nNo quotes are verified, so none will be shown to users.\n"
                      "Check each against its cited source, then:\n"
                      "  python3 scripts/verify_quotes.py verify <quote_id>")
            return 0
        if command == "list":
            pending = db.query(QuoteRecord).filter_by(verification_status="review_needed").all()
            if not pending:
                print("nothing pending review")
            for q in pending:
                print(_line(db, q), "\n")
            return 0
        if command == "show":
            for qid in ids:
                q = db.get(QuoteRecord, qid)
                print(_line(db, q) if q else f"unknown quote: {qid}", "\n")
            return 0
        if command in ("verify", "reject"):
            if not ids:
                print("give at least one quote id")
                return 2
            status = "verified" if command == "verify" else "rejected"
            changed = 0
            for qid in ids:
                q = db.get(QuoteRecord, qid)
                if not q:
                    print(f"unknown quote: {qid}")
                    continue
                q.verification_status = status
                changed += 1
                print(f"{status}: {qid}")
            db.commit()
            print(f"\n{changed} updated")
            return 0
        print(__doc__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
