"""Write helpers that enforce the append-only rule for observations."""
from sqlalchemy.orm import Session

from db.models import Observation


def supersede(session: Session, old: Observation, new: Observation) -> Observation:
    """Replace `old` with `new` without editing or deleting history.

    The live-fact unique index forbids two live rows for the same fact, but `new` needs `old` retired first
    and `old.superseded_by` needs `new.id`. So: retire `old` (pointing at itself for a moment), insert `new`,
    then point `old` at `new`. Runs inside the caller's transaction.
    """
    if old.superseded_by is not None:
        raise ValueError(f"observation {old.id} is already superseded by {old.superseded_by}")
    old.superseded_by = old.id
    session.flush()
    session.add(new)
    session.flush()
    old.superseded_by = new.id
    session.flush()
    return new
