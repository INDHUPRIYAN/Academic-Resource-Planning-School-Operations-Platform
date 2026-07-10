from app.database import SessionLocal
from app import models

db = SessionLocal()
school_id = 1
print(f"School ID: {school_id}")

print("\nTimetable slots for this school:")
for slot in db.query(models.Timetable).filter(models.Timetable.school_id == school_id).all():
    print(f"Slot id={slot.id}, section={slot.section.name if slot.section else None}, subject={slot.subject.name if slot.subject else None}, teacher={slot.teacher.user.name if slot.teacher else None}, day={slot.day_of_week}, period={slot.period}")

print("\nTeachers for this school:")
for t in db.query(models.Teacher).filter(models.Teacher.school_id == school_id).all():
    print(f"Teacher id={t.id}, name={t.user.name}, subjects={[s.id for s in t.subjects]}")

print("\nSubstitutions:")
for s in db.query(models.Substitution).all():
    print(f"Sub id={s.id}, date={s.date}, sub_teacher={s.substitute_teacher.user.name if s.substitute_teacher else None}, method={s.method}, reason={s.reason}")

db.close()
