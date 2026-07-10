import json
import requests
from datetime import date as date_cls, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.auth import get_current_user, require_roles
from app.config import settings
from app.routers.reports import (
    _teacher_workload_data,
    _subject_coverage_data,
    _resource_usage_data,
    _leave_summary_data,
    _resolve_school_id,
)

router = APIRouter(prefix="/assistant", tags=["assistant"])
ADMIN_ROLES = (models.RoleEnum.super_admin, models.RoleEnum.school_admin)

def call_groq(messages: list, tools: list | None = None) -> dict:
    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status_code=502,
            detail="Assistant is unavailable: GROQ_API_KEY is not set"
        )
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
        
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        if r.status_code != 200:
            raise Exception(f"HTTP {r.status_code}: {r.text}")
        return r.json()
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Assistant is unavailable: Groq request failed: {str(e)}"
        )

# Tool definitions for Chat
CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_teacher_workload",
            "description": "Fetch teacher workload and scheduled periods report for the school.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_subject_coverage",
            "description": "Fetch subject scheduling coverage against required hours report.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_resource_usage",
            "description": "Fetch resource usage (classroom, lab, etc.) and booking report.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_leave_summary",
            "description": "Fetch summary of leaves and coverage rate for a date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                    "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"}
                },
                "required": []
            }
        }
    }
]

@router.post("/explain-conflict", response_model=schemas.ExplainConflictResponse)
def explain_conflict(
    req_body: schemas.ExplainConflictRequest,
    user: models.User = Depends(get_current_user),
):
    prompt = (
        f"You are EduFlow AI, an assistant for school scheduling. Explain the following conflict in a friendly, "
        f"plain-English, human-readable way, pointing out why it happened and suggesting potential resolutions. "
        f"Conflict detail: '{req_body.detail}'. "
    )
    if req_body.context:
        prompt += f"Context: {json.dumps(req_body.context)}."
        
    messages = [
        {"role": "system", "content": "You are a helpful school scheduling assistant."},
        {"role": "user", "content": prompt}
    ]
    resp = call_groq(messages)
    reply = resp["choices"][0]["message"].get("content") or ""
    return schemas.ExplainConflictResponse(explanation=reply)

@router.get("/workload-suggestions", response_model=schemas.WorkloadSuggestionsResponse)
def workload_suggestions(
    school_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    sid = _resolve_school_id(user, school_id)
    
    # Fetch workload data and coverage data
    workload = _teacher_workload_data(db, sid)
    coverage = _subject_coverage_data(db, sid)
    
    overloaded_teachers = [t for t in workload if t["overloaded"]]
    under_covered_subjects = [s for s in coverage if s["gap"] > 0]
    
    overloaded_count = len(overloaded_teachers)
    under_covered_count = len(under_covered_subjects)
    
    based_on = {
        "overloaded_count": overloaded_count,
        "under_covered_count": under_covered_count
    }
    
    # If healthy, return canned response without calling Groq
    if overloaded_count == 0 and under_covered_count == 0:
        return schemas.WorkloadSuggestionsResponse(
            based_on=based_on,
            suggestions="All teachers are within their workload limits and all subjects are fully covered. The school's workload distribution is healthy!"
        )
        
    prompt = (
        f"We have overloaded teachers or under-covered subjects. Suggest actionable changes "
        f"(e.g., reassigning subjects, modifying teacher max hours, adjusting timetables) based on this data:\n"
        f"Overloaded Teachers: {json.dumps(overloaded_teachers)}\n"
        f"Under-covered Subjects: {json.dumps(under_covered_subjects)}\n"
    )
    
    messages = [
        {"role": "system", "content": "You are a helpful school scheduling assistant providing workload optimization suggestions."},
        {"role": "user", "content": prompt}
    ]
    
    resp = call_groq(messages)
    reply = resp["choices"][0]["message"].get("content") or ""
    return schemas.WorkloadSuggestionsResponse(based_on=based_on, suggestions=reply)

@router.post("/narrate-report", response_model=schemas.NarrateReportResponse)
def narrate_report(
    req_body: schemas.NarrateReportRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    sid = _resolve_school_id(user, req_body.school_id)
    
    valid_types = {"teacher-workload", "subject-coverage", "resource-usage", "leave-summary", "timetables"}
    if req_body.report_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid report_type: {req_body.report_type}")
        
    start = req_body.start_date
    end = req_body.end_date
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")
        
    if req_body.report_type == "teacher-workload":
        data = _teacher_workload_data(db, sid)
    elif req_body.report_type == "subject-coverage":
        data = _subject_coverage_data(db, sid)
    elif req_body.report_type == "resource-usage":
        data = _resource_usage_data(db, sid)
    elif req_body.report_type == "leave-summary":
        end_val = end or date_cls.today()
        start_val = start or (end_val - timedelta(days=30))
        data = _leave_summary_data(db, sid, start_val, end_val)
    else:  # timetables
        slots = db.query(models.Timetable).filter(models.Timetable.school_id == sid).all()
        data = [{"day": s.day_of_week, "period": s.period, "teacher_id": s.teacher_id, "subject_id": s.subject_id} for s in slots]
        
    prompt = (
        f"Summarize the following '{req_body.report_type}' report in a short, professional prose narrative. "
        f"Point out any key insights, patterns, or areas of concern. Report Data:\n{json.dumps(data)}"
    )
    
    messages = [
        {"role": "system", "content": "You are a helpful school administration analyst assistant."},
        {"role": "user", "content": prompt}
    ]
    
    resp = call_groq(messages)
    reply = resp["choices"][0]["message"].get("content") or ""
    return schemas.NarrateReportResponse(narrative=reply)

@router.post("/chat", response_model=schemas.ChatResponse)
def assistant_chat(
    req_body: schemas.ChatRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    school_id = _resolve_school_id(user, req_body.school_id)
    
    messages = [
        {
            "role": "system",
            "content": (
                "You are EduFlow AI, an intelligent assistant for school management. "
                "You have access to current school reports. Provide clear, concise, and helpful answers."
            )
        },
        {"role": "user", "content": req_body.message}
    ]
    
    for _ in range(5):
        resp = call_groq(messages, tools=CHAT_TOOLS)
        choice = resp["choices"][0]
        message = choice["message"]
        
        if "tool_calls" not in message or not message["tool_calls"]:
            return schemas.ChatResponse(reply=message.get("content") or "")
            
        messages.append(message)
        
        for tool_call in message["tool_calls"]:
            func_name = tool_call["function"]["name"]
            func_args = json.loads(tool_call["function"]["arguments"] or "{}")
            tool_call_id = tool_call["id"]
            
            try:
                if func_name == "get_teacher_workload":
                    data = _teacher_workload_data(db, school_id)
                elif func_name == "get_subject_coverage":
                    data = _subject_coverage_data(db, school_id)
                elif func_name == "get_resource_usage":
                    data = _resource_usage_data(db, school_id)
                elif func_name == "get_leave_summary":
                    end_val = date_cls.today()
                    start_val = end_val - timedelta(days=30)
                    if "start_date" in func_args:
                        start_val = date_cls.fromisoformat(func_args["start_date"])
                    if "end_date" in func_args:
                        end_val = date_cls.fromisoformat(func_args["end_date"])
                    data = _leave_summary_data(db, school_id, start_val, end_val)
                else:
                    data = {"error": f"Unknown tool: {func_name}"}
            except Exception as e:
                data = {"error": f"Failed to execute tool: {str(e)}"}
                
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": func_name,
                "content": json.dumps(data)
            })
            
    return schemas.ChatResponse(reply="I encountered a loop limit or could not summarize the details.")


@router.post("/explain-infeasibility", response_model=schemas.ExplainInfeasibilityResponse)
def explain_infeasibility(
    req_body: schemas.ExplainInfeasibilityRequest,
    user: models.User = Depends(get_current_user),
):
    prompt = (
        f"You are EduFlow AI, an enterprise-level school scheduling assistant. "
        f"The CP-SAT solver failed to generate a timetable due to one or more mathematical constraints "
        f"or conflicts in the school setup. Explain exactly why these conflicts block scheduling "
        f"and suggest actionable resolutions. Here is the list of validation errors/blockers:\n"
        f"{json.dumps(req_body.errors)}\n"
    )
    if req_body.warnings:
        prompt += f"Warnings to keep in mind: {json.dumps(req_body.warnings)}.\n"
        
    messages = [
        {"role": "system", "content": "You are a helpful school scheduling constraint solver expert."},
        {"role": "user", "content": prompt}
    ]
    resp = call_groq(messages)
    reply = resp["choices"][0]["message"].get("content") or ""
    return schemas.ExplainInfeasibilityResponse(explanation=reply)


@router.post("/suggestions", response_model=schemas.AssistantSuggestionsResponse)
def get_ai_suggestions(
    payload: schemas.AssistantSuggestionsRequest,
    user: models.User = Depends(get_current_user),
):
    conflicts_desc = []
    for c in payload.conflicts:
        conflicts_desc.append(
            f"- Problem: {c.problem}\n  Reason: {c.reason}\n  Proposed Fix: {c.suggested_fix}\n  Auto Fix Available: {c.auto_fix_available}\n  Impact: {c.estimated_impact}"
        )
    
    joined_conflicts = "\n".join(conflicts_desc)
    prompt = (
        f"You are EduFlow AI. An administrator is facing the following scheduling conflicts:\n"
        f"{joined_conflicts}\n\n"
        f"Generate a clear narrative explaining these conflicts, and return a list of suggestions. "
        f"Provide the response in JSON format matching this EXACT structure (include ONLY valid JSON in your response):\n"
        f"{{\n"
        f"  \"narrative\": \"A friendly explanation of the conflicts.\",\n"
        f"  \"suggestions\": [\n"
        f"    {{\n"
        f"      \"conflict_problem\": \"Problem text\",\n"
        f"      \"actionable_step\": \"Step-by-step resolution strategy\",\n"
        f"      \"confidence_pct\": 95\n"
        f"    }}\n"
        f"  ]\n"
        f"}}"
    )

    messages = [
        {"role": "system", "content": "You are a helpful school scheduling constraint solver expert. You must reply with a valid JSON document matching the requested structure."},
        {"role": "user", "content": prompt}
    ]
    
    resp = call_groq(messages)
    content = resp["choices"][0]["message"].get("content") or ""
    content = content.replace("```json", "").replace("```", "").strip()
    
    try:
        parsed = json.loads(content)
        return schemas.AssistantSuggestionsResponse(
            narrative=parsed.get("narrative", "Here are the suggested fixes for the conflicts:"),
            suggestions=parsed.get("suggestions", [])
        )
    except Exception:
        return schemas.AssistantSuggestionsResponse(
            narrative=content,
            suggestions=[{
                "conflict_problem": "General Conflict",
                "actionable_step": "Please review conflict parameters manually in Settings or Assignments.",
                "confidence_pct": 80
            }]
        )
