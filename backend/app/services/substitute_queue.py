"""Ranked substitute queue (writer side).

The engine (substitution_engine.rank_substitutes) scores every eligible teacher and
returns the whole ranked list. This module persists that list and manages the queue:

    rank 1  -> assigned  (a Substitution row is created)
    rank 2+ -> backup    (waiting, visible to everyone)

If the assigned teacher declines with a valid reason, the next backup is promoted
automatically, with no re-solve and no admin round-trip.

Policy: a free period is NOT a valid reason to decline - free periods belong to the
institution. The caller enforces that; this module just records the reason given.
"""
from datetime import date as date_cls

from sqlalchemy.orm import Session, joinedload

from app import models
from app.substitution_engine import rank_substitutes


def build_queue(
    db: Session,
    slot: models.Timetable,
    on_date: date_cls,
    absent_teacher_id: int,
    leave_id: int | None = None,
    on_duty_id: int | None = None,
) -> tuple[models.Substitution | None, list[models.SubstituteCandidate], str]:
    """Rank every eligible teacher, store the queue, and auto-assign rank 1.

    Returns (substitution_or_None, candidate_rows, message). Caller should db.flush()
    afterwards so the next slot's eligibility check sees this assignment."""
    # A rebuild supersedes any previous queue for this exact slot+date.
    db.query(models.SubstituteCandidate).filter(
        models.SubstituteCandidate.timetable_id == slot.id,
        models.SubstituteCandidate.date == on_date,
    ).update({"status": models.CandidateStatus.superseded}, synchronize_session=False)

    ranked = rank_substitutes(db, slot, on_date, absent_teacher_id)
    if not ranked:
        return None, [], (
            "No teacher is both free and available at this period. Covering it would "
            "double-book someone or use a teacher outside their availability, so it is "
            "left for manual assignment."
        )

    rows: list[models.SubstituteCandidate] = []
    for rc in ranked:
        rows.append(models.SubstituteCandidate(
            timetable_id=slot.id,
            date=on_date,
            teacher_id=rc.teacher_id,
            rank=rc.rank,
            score=rc.score,
            method=rc.method,
            reason=rc.reason,
            status=models.CandidateStatus.assigned if rc.rank == 1 else models.CandidateStatus.backup,
            leave_id=leave_id,
            on_duty_id=on_duty_id,
        ))
    for r in rows:
        db.add(r)

    top = ranked[0]
    sub = models.Substitution(
        leave_id=leave_id,
        on_duty_id=on_duty_id,
        timetable_id=slot.id,
        substitute_teacher_id=top.teacher_id,
        date=on_date,
        method=top.method,
        reason=top.reason,
        rank=top.rank,
        score=top.score,
        assigned_by=None,
    )
    db.add(sub)
    db.flush()
    return sub, rows, f"{top.teacher_name} assigned (rank 1 of {len(ranked)}, score {top.score}%)."


def queue_for(db: Session, timetable_id: int, on_date: date_cls) -> list[models.SubstituteCandidate]:
    return (
        db.query(models.SubstituteCandidate)
        .options(joinedload(models.SubstituteCandidate.teacher).joinedload(models.Teacher.user))
        .filter(
            models.SubstituteCandidate.timetable_id == timetable_id,
            models.SubstituteCandidate.date == on_date,
            models.SubstituteCandidate.status != models.CandidateStatus.superseded,
        )
        .order_by(models.SubstituteCandidate.rank)
        .all()
    )


def promote_next(
    db: Session,
    sub: models.Substitution,
    decline_reason: str,
) -> tuple[models.Substitution | None, str]:
    """The assigned teacher stepped aside. Mark them declined and promote the next
    backup who is STILL eligible (their situation may have changed since the queue was
    built - they may since have gone on leave or picked up another cover)."""
    queue = queue_for(db, sub.timetable_id, sub.date)
    current = next((c for c in queue if c.teacher_id == sub.substitute_teacher_id), None)
    if current:
        current.status = models.CandidateStatus.declined
        current.decline_reason = decline_reason

    declined_ids = {c.teacher_id for c in queue if c.status == models.CandidateStatus.declined}
    declined_ids.add(sub.substitute_teacher_id)

    slot = db.query(models.Timetable).filter(models.Timetable.id == sub.timetable_id).first()
    # Re-rank excluding everyone who has declined, so eligibility is re-checked fresh.
    ranked = rank_substitutes(db, slot, sub.date, _absent_teacher_of(db, sub), exclude_teacher_ids=declined_ids)
    if not ranked:
        db.delete(sub)
        db.flush()
        return None, ("No remaining teacher is free and available for this period. "
                      "It now needs a manual assignment.")

    nxt = ranked[0]
    # Refresh the stored queue so the ranks reflect reality.
    for c in queue:
        if c.teacher_id == nxt.teacher_id:
            c.status = models.CandidateStatus.assigned
        elif c.status == models.CandidateStatus.assigned:
            c.status = models.CandidateStatus.backup

    sub.substitute_teacher_id = nxt.teacher_id
    sub.method = nxt.method
    sub.reason = nxt.reason
    sub.rank = nxt.rank
    sub.score = nxt.score
    sub.decline_reason = decline_reason
    db.flush()
    return sub, f"{nxt.teacher_name} promoted from the backup queue (score {nxt.score}%)."


def _absent_teacher_of(db: Session, sub: models.Substitution) -> int:
    """Whose class is being covered - the master timetable's owner for that slot."""
    slot = db.query(models.Timetable).filter(models.Timetable.id == sub.timetable_id).first()
    return slot.teacher_id if slot and slot.teacher_id else -1
