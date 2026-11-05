"""Ghost Data audit API: serves only the supplied dataset, evidence, and output."""

import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import code.data_service as data_service
from code.ai_agent import ai_agent

app = FastAPI(title="Ghost Data Deletion Audit", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class InvestigateRequest(BaseModel):
    case_id: str


class AskRequest(BaseModel):
    case_id: str
    question: str


@app.get("/api/health")
def health():
    files = data_service.list_dataset_files()
    output = data_service.get_output_table(1, 1)
    return {
        "status": "ok",
        "dataset_csv_count": len(files),
        "request_count": next((item["rows"] for item in files if item["name"] == "deletion_requests.csv"), 0),
        "evidence_file_count": len(data_service.list_evidence()),
        "output_rows": output["total_rows"],
        "output_valid": output["validation"]["valid"],
    }


@app.get("/api/overview")
def overview():
    files = data_service.list_dataset_files()
    evidence = data_service.list_evidence()
    try:
        output = data_service.get_output_table(1, 1000)
        validation = output["validation"]
        output_count = output["total_rows"]
    except FileNotFoundError:
        validation, output_count = {"valid": False, "errors": ["output.csv has not been generated."]}, 0
    return {
        "dataset_files": files,
        "dataset_file_count": len(files),
        "evidence_file_count": len(evidence),
        "output_rows": output_count,
        "output_validation": validation,
    }


@app.get("/api/datasets")
def datasets():
    return {"files": data_service.list_dataset_files()}


@app.get("/api/datasets/table/{relative_path:path}")
def dataset_table(
    relative_path: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    search: str = Query(default=""),
):
    try:
        return data_service.get_csv_table(relative_path, page, page_size, search)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/cases/{case_id}")
def case_detail(case_id: str):
    case = data_service.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No deletion request exists for {case_id}.")
    case_id_info = ai_agent.tool_get_identity_information(case_id=case_id)
    user_id = case_id_info.get("primary_identity")
    audit_rows = []
    if user_id:
        _, rows = data_service._read_csv(data_service.DATASET / "user_audit_log.csv")
        audit_rows = [row for row in rows if row.get("user_id") == user_id]
    return {
        **case,
        "identity": case_id_info,
        "identity_history": audit_rows,
        "activity": ai_agent.tool_get_system_activity(case_id=case_id, user_id=user_id),
        "evidence_matches": ai_agent.tool_search_case_evidence(case_id=case_id, user_id=user_id),
    }


@app.get("/api/evidence")
def evidence_list():
    return {"files": data_service.list_evidence()}


@app.get("/api/evidence/{file_id}")
def evidence_detail(file_id: str):
    try:
        result = data_service.get_evidence(file_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Evidence file {file_id} is not in evidence_files.csv.")
    return result


@app.get("/api/evidence/{file_id}/file")
def evidence_file(file_id: str):
    _, manifest = data_service._read_csv(data_service.DATASET / "evidence_files.csv")
    row = next((entry for entry in manifest if entry.get("file_id") == file_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Evidence file {file_id} is not in evidence_files.csv.")
    try:
        path = data_service._inside_dataset(row["file_path"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Evidence file is missing: {row['file_path']}.")
    return FileResponse(path, filename=path.name)


@app.get("/api/output")
def output_table(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
):
    try:
        return data_service.get_output_table(page, page_size)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Root output.csv has not been generated yet.") from exc


@app.get("/api/download/output.csv")
def download_output():
    if not data_service.OUTPUT_CSV.is_file():
        raise HTTPException(status_code=404, detail="Root output.csv has not been generated yet.")
    return FileResponse(data_service.OUTPUT_CSV, media_type="text/csv", filename="output.csv")


@app.post("/api/output/generate")
def generate_output():
    command = [sys.executable, str(ROOT / "code" / "main.py")]
    try:
        subprocess.run(command, check=True, cwd=ROOT, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        details = (exc.stdout or "") + (exc.stderr or "")
        raise HTTPException(status_code=422, detail={
            "message": "CSV generation or contract validation failed.",
            "run_output": details[-12000:],
        }) from exc
    return data_service.get_output_table(1, 1)["validation"]


@app.get("/api/ai-agent/status")
def ai_status():
    return ai_agent.get_agent_status()


@app.post("/api/ai-agent/investigate")
def investigate(request: InvestigateRequest):
    result = ai_agent.execute_investigation(request.case_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.post("/api/ai-agent/chat")
def ask(request: AskRequest):
    result = ai_agent.answer_case_question(request.case_id, request.question)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])
    return result


DOCS_DIR = ROOT / "docs"
if DOCS_DIR.is_dir():
    app.mount("/", StaticFiles(directory=DOCS_DIR, html=True), name="frontend")


def start_server(host: str = "0.0.0.0", port: int = 8001):
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server()
