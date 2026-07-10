"""
Reports (Phase 7).

Purpose-built router (like timetables.py/leaves.py/swaps.py/exams.py) since
these are aggregation queries + PDF/Excel export, not plain CRUD. Five
report types, each with a JSON endpoint (for the on-screen table) and an
export endpoint (PDF or Excel, same filters):

  GET /reports/teacher-workload   GET /reports/export/teacher-workload
  GET /reports/subject-coverage   GET /reports/export/subject-coverage
  GET /reports/resource-usage     GET /reports/export/resource-usage
  GET /reports/leave-summary      GET /reports/export/leave-summary
  GET /reports/timetable          GET /reports/export/timetable

All admin-only (super_admin/school_admin) — reports aggregate across an
entire school, which isn't a teacher's own data. school_id is required for
super_admin (who isn't scoped to one school) and implied by the caller's
own school_id otherwise, same convention as exams.py's generator.
"""
from datetime import date as date_cls, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.auth import require_roles
from app.crud_factory import log_action
from app.substitution_engine import leave_date_range
from app.services import report_export
from app import models

router = APIRouter(prefix="/reports", tags=["reports"])
ADMIN_ROLES = (models.RoleEnum.super_admin, models.RoleEnum.school_admin)

EXPORT_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _resolve_school_id(user: models.User, school_id: int | None) -> int:
    if user.role == models.RoleEnum.super_admin:
        if not school_id:
            raise HTTPException(status_code=400, detail="school_id is required for super_admin")
        return school_id
    return user.school_id


def _get_school_or_404(db: Session, school_id: int) -> models.School:
    school = db.query(models.School).filter(models.School.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    return school


def _export_response(fmt: str, *, filename: str, title: str, subtitle: str, headers: list[str], rows: list[list]):
    if fmt not in EXPORT_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="format must be 'pdf' or 'xlsx'")
    if fmt == "pdf":
        content = report_export.rows_to_pdf(title=title, subtitle=subtitle, headers=headers, rows=rows)
    else:
        content = report_export.rows_to_xlsx(title=title, headers=headers, rows=rows)
    return Response(
        content=content,
        media_type=EXPORT_MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}.{fmt}"'},
    )


# ---------------------------------------------------------------- Teacher Workload

def _teacher_workload_data(db: Session, school_id: int) -> list[dict]:
    teachers = (
        db.query(models.Teacher)
        .options(joinedload(models.Teacher.user), joinedload(models.Teacher.subjects))
        .filter(models.Teacher.school_id == school_id)
        .all()
    )
    out = []
    for t in teachers:
        slots = db.query(models.Timetable).filter(
            models.Timetable.teacher_id == t.id, models.Timetable.subject_id.isnot(None)
        ).all()
        scheduled_periods = len(slots)
        section_ids = {s.section_id for s in slots}
        subject_ids = {s.subject_id for s in slots}
        max_hours = t.max_weekly_hours or 0
        utilization_pct = round(scheduled_periods / max_hours * 100, 1) if max_hours else None
        out.append({
            "teacher_id": t.id,
            "teacher_name": t.user.name if t.user else "",
            "department": t.department or "",
            "scheduled_periods": scheduled_periods,
            "max_weekly_hours": max_hours,
            "utilization_pct": utilization_pct,
            "sections_taught": len(section_ids),
            "subjects_taught": len(subject_ids),
            "subject_names": sorted({s.name for s in t.subjects}) if t.subjects else [],
            "overloaded": bool(max_hours) and scheduled_periods > max_hours,
        })
    out.sort(key=lambda r: r["scheduled_periods"], reverse=True)
    return out


@router.get("/teacher-workload")
def teacher_workload(
    school_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    sid = _resolve_school_id(user, school_id)
    _get_school_or_404(db, sid)
    rows = _teacher_workload_data(db, sid)
    overloaded = sum(1 for r in rows if r["overloaded"])
    avg_util = round(sum(r["utilization_pct"] or 0 for r in rows) / len(rows), 1) if rows else 0
    return {"school_id": sid, "teachers": rows, "summary": {"teacher_count": len(rows), "overloaded_count": overloaded, "avg_utilization_pct": avg_util}}


@router.get("/export/teacher-workload")
def export_teacher_workload(
    format: str = Query("pdf"),
    school_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    sid = _resolve_school_id(user, school_id)
    school = _get_school_or_404(db, sid)
    rows = _teacher_workload_data(db, sid)
    headers = ["Teacher", "Department", "Scheduled Periods/wk", "Max Weekly Hours", "Utilization %", "Sections", "Subjects", "Overloaded"]
    table_rows = [[
        r["teacher_name"], r["department"], r["scheduled_periods"], r["max_weekly_hours"],
        r["utilization_pct"] if r["utilization_pct"] is not None else "—",
        r["sections_taught"], r["subjects_taught"], "Yes" if r["overloaded"] else "No",
    ] for r in rows]
    log_action(db, user.id, "export_report", f"teacher_workload school_id={sid} format={format}")
    return _export_response(format, filename=f"teacher_workload_{school.name.replace(' ', '_')}",
                             title="Teacher Workload Report", subtitle=f"{school.name}", headers=headers, rows=table_rows)


# ---------------------------------------------------------------- Subject Coverage

def _subject_coverage_data(db: Session, school_id: int) -> list[dict]:
    sections = (
        db.query(models.Section)
        .join(models.Class, models.Section.class_id == models.Class.id)
        .options(joinedload(models.Section.class_))
        .filter(models.Class.school_id == school_id)
        .all()
    )
    subjects = db.query(models.Subject).filter(models.Subject.school_id == school_id).all()
    out = []
    for section in sections:
        for subject in subjects:
            scheduled = db.query(models.Timetable).filter(
                models.Timetable.section_id == section.id, models.Timetable.subject_id == subject.id
            ).count()
            if scheduled == 0 and subject.weekly_hours == 0:
                continue
            required = subject.weekly_hours or 0
            coverage_pct = round(scheduled / required * 100, 1) if required else None
            out.append({
                "section_id": section.id,
                "section_name": f"{section.class_.name} {section.name}" if section.class_ else section.name,
                "subject_id": subject.id,
                "subject_name": subject.name,
                "required_weekly_hours": required,
                "scheduled_periods": scheduled,
                "coverage_pct": coverage_pct,
                "gap": max(required - scheduled, 0),
            })
    out.sort(key=lambda r: (r["coverage_pct"] if r["coverage_pct"] is not None else 999))
    return out


@router.get("/subject-coverage")
def subject_coverage(
    school_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    sid = _resolve_school_id(user, school_id)
    _get_school_or_404(db, sid)
    rows = _subject_coverage_data(db, sid)
    under_covered = sum(1 for r in rows if r["gap"] > 0)
    return {"school_id": sid, "rows": rows, "summary": {"pair_count": len(rows), "under_covered_count": under_covered}}


@router.get("/export/subject-coverage")
def export_subject_coverage(
    format: str = Query("pdf"),
    school_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    sid = _resolve_school_id(user, school_id)
    school = _get_school_or_404(db, sid)
    rows = _subject_coverage_data(db, sid)
    headers = ["Section", "Subject", "Required Hours/wk", "Scheduled Periods/wk", "Coverage %", "Gap"]
    table_rows = [[
        r["section_name"], r["subject_name"], r["required_weekly_hours"], r["scheduled_periods"],
        r["coverage_pct"] if r["coverage_pct"] is not None else "—", r["gap"],
    ] for r in rows]
    log_action(db, user.id, "export_report", f"subject_coverage school_id={sid} format={format}")
    return _export_response(format, filename=f"subject_coverage_{school.name.replace(' ', '_')}",
                             title="Subject Coverage Report", subtitle=f"{school.name}", headers=headers, rows=table_rows)


# ---------------------------------------------------------------- Resource Usage

def _resource_usage_data(db: Session, school_id: int) -> list[dict]:
    school = _get_school_or_404(db, school_id)
    max_weekly_slots = (school.periods_per_day or 0) * (school.working_days or 0)
    resources = db.query(models.Resource).filter(models.Resource.school_id == school_id).all()
    out = []
    for r in resources:
        timetable_bookings = db.query(models.Timetable).filter(models.Timetable.resource_id == r.id).count()
        exam_bookings = db.query(models.Exam).filter(models.Exam.resource_id == r.id).count()
        utilization_pct = round(timetable_bookings / max_weekly_slots * 100, 1) if max_weekly_slots else None
        out.append({
            "resource_id": r.id,
            "name": r.name,
            "type": r.type or "",
            "capacity": r.capacity,
            "timetable_bookings_per_week": timetable_bookings,
            "exam_bookings": exam_bookings,
            "utilization_pct": utilization_pct,
        })
    out.sort(key=lambda r: r["timetable_bookings_per_week"], reverse=True)
    return out


@router.get("/resource-usage")
def resource_usage(
    school_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    sid = _resolve_school_id(user, school_id)
    rows = _resource_usage_data(db, sid)
    unused = sum(1 for r in rows if r["timetable_bookings_per_week"] == 0 and r["exam_bookings"] == 0)
    return {"school_id": sid, "resources": rows, "summary": {"resource_count": len(rows), "unused_count": unused}}


@router.get("/export/resource-usage")
def export_resource_usage(
    format: str = Query("pdf"),
    school_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    sid = _resolve_school_id(user, school_id)
    school = _get_school_or_404(db, sid)
    rows = _resource_usage_data(db, sid)
    headers = ["Resource", "Type", "Capacity", "Timetable Bookings/wk", "Exam Bookings", "Utilization %"]
    table_rows = [[
        r["name"], r["type"], r["capacity"] if r["capacity"] is not None else "—",
        r["timetable_bookings_per_week"], r["exam_bookings"],
        r["utilization_pct"] if r["utilization_pct"] is not None else "—",
    ] for r in rows]
    log_action(db, user.id, "export_report", f"resource_usage school_id={sid} format={format}")
    return _export_response(format, filename=f"resource_usage_{school.name.replace(' ', '_')}",
                             title="Resource Usage Report", subtitle=f"{school.name}", headers=headers, rows=table_rows)


# ---------------------------------------------------------------- Leave Summary

def _leave_summary_data(db: Session, school_id: int, start: date_cls, end: date_cls) -> dict:
    leaves = (
        db.query(models.Leave)
        .options(joinedload(models.Leave.teacher).joinedload(models.Teacher.user))
        .filter(
            models.Leave.school_id == school_id,
            models.Leave.date <= end,
            (models.Leave.end_date.isnot(None) & (models.Leave.end_date >= start)) | (models.Leave.end_date.is_(None) & (models.Leave.date >= start)),
        )
        .all()
    )

    by_status = {"pending": 0, "approved": 0, "rejected": 0}
    per_teacher: dict[int, dict] = {}
    total_slots_needing_coverage = 0
    total_covered = 0

    for lv in leaves:
        status_key = lv.status.value if hasattr(lv.status, "value") else str(lv.status)
        by_status[status_key] = by_status.get(status_key, 0) + 1

        tname = lv.teacher.user.name if lv.teacher and lv.teacher.user else "Unknown"
        entry = per_teacher.setdefault(lv.teacher_id, {"teacher_id": lv.teacher_id, "teacher_name": tname, "requests": 0, "approved_days": 0, "pending": 0, "rejected": 0})
        entry["requests"] += 1
        entry[status_key] = entry.get(status_key, 0) + 1

        if lv.status == models.LeaveStatus.approved:
            dates_in_range = [d for d in leave_date_range(lv) if start <= d <= end]
            entry["approved_days"] += len(dates_in_range)
            for on_date in dates_in_range:
                day_of_week = on_date.weekday()
                slots = db.query(models.Timetable).filter(
                    models.Timetable.teacher_id == lv.teacher_id,
                    models.Timetable.day_of_week == day_of_week,
                    models.Timetable.subject_id.isnot(None),
                ).all()
                total_slots_needing_coverage += len(slots)
                for slot in slots:
                    covered = db.query(models.Substitution).filter(
                        models.Substitution.timetable_id == slot.id, models.Substitution.date == on_date
                    ).first()
                    if covered:
                        total_covered += 1

    coverage_rate_pct = round(total_covered / total_slots_needing_coverage * 100, 1) if total_slots_needing_coverage else None
    return {
        "by_status": by_status,
        "per_teacher": sorted(per_teacher.values(), key=lambda r: r["requests"], reverse=True),
        "total_requests": len(leaves),
        "slots_needing_coverage": total_slots_needing_coverage,
        "slots_covered": total_covered,
        "coverage_rate_pct": coverage_rate_pct,
    }


@router.get("/leave-summary")
def leave_summary(
    start_date: date_cls | None = None,
    end_date: date_cls | None = None,
    school_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    sid = _resolve_school_id(user, school_id)
    _get_school_or_404(db, sid)
    end = end_date or date_cls.today()
    start = start_date or (end - timedelta(days=30))
    if start > end:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")
    data = _leave_summary_data(db, sid, start, end)
    return {"school_id": sid, "start_date": start, "end_date": end, **data}


@router.get("/export/leave-summary")
def export_leave_summary(
    format: str = Query("pdf"),
    start_date: date_cls | None = None,
    end_date: date_cls | None = None,
    school_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    sid = _resolve_school_id(user, school_id)
    school = _get_school_or_404(db, sid)
    end = end_date or date_cls.today()
    start = start_date or (end - timedelta(days=30))
    if start > end:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")
    data = _leave_summary_data(db, sid, start, end)
    headers = ["Teacher", "Requests", "Approved", "Pending", "Rejected", "Approved Days in Range"]
    table_rows = [[
        r["teacher_name"], r["requests"], r.get("approved", 0), r.get("pending", 0), r.get("rejected", 0), r["approved_days"],
    ] for r in data["per_teacher"]]
    log_action(db, user.id, "export_report", f"leave_summary school_id={sid} format={format}")
    subtitle = f"{school.name} — {start.isoformat()} to {end.isoformat()} — coverage rate: {data['coverage_rate_pct']}%" if data["coverage_rate_pct"] is not None else f"{school.name} — {start.isoformat()} to {end.isoformat()}"
    return _export_response(format, filename=f"leave_summary_{school.name.replace(' ', '_')}",
                             title="Leave Summary Report", subtitle=subtitle, headers=headers, rows=table_rows)


# ---------------------------------------------------------------- Timetables

def _timetable_grid_data(db: Session, *, section_id: int | None, teacher_id: int | None):
    if not section_id and not teacher_id:
        raise HTTPException(status_code=400, detail="Provide either section_id or teacher_id")
    query = db.query(models.Timetable).options(
        joinedload(models.Timetable.section).joinedload(models.Section.class_),
        joinedload(models.Timetable.subject),
        joinedload(models.Timetable.teacher).joinedload(models.Teacher.user),
        joinedload(models.Timetable.activity),
        joinedload(models.Timetable.resource),
    )
    if section_id:
        query = query.filter(models.Timetable.section_id == section_id)
    else:
        query = query.filter(models.Timetable.teacher_id == teacher_id)
    rows = query.all()
    if not rows:
        raise HTTPException(status_code=404, detail="No master timetable slots found for this filter")

    school_id = rows[0].school_id
    school = _get_school_or_404(db, school_id)

    cells = {}
    periods = sorted({r.period for r in rows}) or list(range(1, (school.periods_per_day or 8) + 1))
    for r in rows:
        if r.activity_id:
            label = r.activity.name if r.activity else "Activity"
        elif r.subject_id:
            subj = r.subject.name if r.subject else ""
            if teacher_id:
                # Grid is per-teacher: show subject + which section it's taught to.
                other = f"{r.section.class_.name} {r.section.name}" if r.section and r.section.class_ else ""
            else:
                # Grid is per-section: show subject + who teaches it.
                other = r.teacher.user.name if r.teacher and r.teacher.user else ""
            label = f"{subj}\n{other}" if other else subj
        else:
            label = "Free"
        cells[(r.day_of_week, r.period)] = label

    if section_id:
        title_subject = f"{rows[0].section.class_.name} {rows[0].section.name}" if rows[0].section and rows[0].section.class_ else f"Section {section_id}"
        subtitle = f"{school.name} — Section {title_subject}"
    else:
        tname = rows[0].teacher.user.name if rows[0].teacher and rows[0].teacher.user else f"Teacher {teacher_id}"
        subtitle = f"{school.name} — {tname}"

    return {
        "school": school, "periods": periods, "working_days": school.working_days or 5,
        "cells": cells, "subtitle": subtitle,
    }


@router.get("/timetable")
def timetable_report(
    section_id: int | None = None,
    teacher_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    data = _timetable_grid_data(db, section_id=section_id, teacher_id=teacher_id)
    grid = []
    for p in data["periods"]:
        row = {"period": p, "days": []}
        for d in range(data["working_days"]):
            row["days"].append(data["cells"].get((d, p), ""))
        grid.append(row)
    return {"subtitle": data["subtitle"], "working_days": data["working_days"], "periods": data["periods"], "grid": grid}


@router.get("/export/timetable")
def export_timetable_report(
    format: str = Query("pdf"),
    section_id: int | None = None,
    teacher_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    data = _timetable_grid_data(db, section_id=section_id, teacher_id=teacher_id)
    if format not in EXPORT_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="format must be 'pdf' or 'xlsx'")
    label = f"section_{section_id}" if section_id else f"teacher_{teacher_id}"
    if format == "pdf":
        content = report_export.grid_to_pdf(title="Timetable", subtitle=data["subtitle"], periods=data["periods"], working_days=data["working_days"], cells=data["cells"])
    else:
        content = report_export.grid_to_xlsx(title="Timetable", periods=data["periods"], working_days=data["working_days"], cells=data["cells"])
    log_action(db, user.id, "export_report", f"timetable {label} format={format}")
    return Response(
        content=content,
        media_type=EXPORT_MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="timetable_{label}.{format}"'},
    )
