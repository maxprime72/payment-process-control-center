import os
import sys
import io
from contextlib import asynccontextmanager
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, List

from models import (
    DatasetInfo,
    KPIData,
    ChartsData,
    ExcelPreviewResponse,
    DataQualitySummary,
)
from services.db_service import (
    init_db,
    get_db,
    checkpoint_database,
    replace_active_dataset,
    get_active_dataset,
    get_dataset_history,
    get_kpis_data,
    get_charts_data,
    get_invoices_paged,
    get_invoice_by_id,
    get_filter_options,
    get_action_required_list,
    get_data_quality_report,
)
from services.excel_service import (
    preview_excel_file,
    parse_and_normalize_data,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    checkpoint_database()

app = FastAPI(
    title="Nabinagar Payment Process Control Center API",
    description="Reusable Excel-driven payment management and process control backend",
    version="2.0.0",
    lifespan=lifespan
)

# Enable CORS for frontend Vite dev server (and any local port)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "Nabinagar Payment Process Control Center"}

@app.get("/api/dataset/current")
def get_current_dataset(db: Session = Depends(get_db)):
    active_ds = get_active_dataset(db)
    if not active_ds:
        return {"active": False, "dataset": None}

    uploaded_at_val = getattr(active_ds, "uploaded_at", None)
    uploaded_at_str = ""
    if uploaded_at_val is not None and hasattr(uploaded_at_val, "strftime"):
        uploaded_at_str = uploaded_at_val.strftime("%Y-%m-%d %H:%M:%S")

    return {
        "active": True,
        "dataset": {
            "id": getattr(active_ds, "id"),
            "filename": str(getattr(active_ds, "filename", "")),
            "sheet_name": str(getattr(active_ds, "sheet_name", "")),
            "uploaded_at": uploaded_at_str,
            "total_records": getattr(active_ds, "total_records", 0),
            "total_invoice_value": getattr(active_ds, "total_invoice_value", 0.0),
            "total_amount_payable": getattr(active_ds, "total_amount_payable", 0.0),
            "is_active": bool(getattr(active_ds, "is_active", True)),
        },
    }

@app.get("/api/dataset/history")
def get_history(db: Session = Depends(get_db)):
    return get_dataset_history(db)

@app.post("/api/upload/preview")
async def preview_upload(file: UploadFile = File(...)):
    filename = file.filename or ""
    if not (filename.endswith(".xlsx") or filename.endswith(".xls")):
        raise HTTPException(status_code=400, detail="Only .xlsx and .xls files are supported.")

    content = await file.read()
    try:
        preview = preview_excel_file(content, filename)
        return preview
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to inspect Excel file: {str(e)}")

@app.post("/api/upload/confirm")
async def confirm_upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = file.filename or ""
    if not (filename.endswith(".xlsx") or filename.endswith(".xls")):
        raise HTTPException(status_code=400, detail="Only .xlsx and .xls files are supported.")

    content = await file.read()
    try:
        records, meta = parse_and_normalize_data(content, filename)
        dataset = replace_active_dataset(db, filename, meta["sheet_name"], records)
        return {
            "success": True,
            "message": f"Dashboard updated successfully from {filename}",
            "dataset_id": dataset.id,
            "total_records": dataset.total_records,
            "total_invoice_value": dataset.total_invoice_value,
        }
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")

@app.post("/api/upload/load-default")
def load_default_file(db: Session = Depends(get_db)):
    """Loads the workspace Pay.xlsx file if available."""
    app_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    bundle_dir = getattr(sys, "_MEIPASS", app_dir)
    possible_paths = [
        os.path.join(app_dir, "Pay.xlsx"),
        os.path.join(app_dir, "data", "Pay.xlsx"),
        os.path.join(bundle_dir, "Pay.xlsx"),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Pay.xlsx")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "Pay.xlsx")),
    ]

    found_path = None
    for p in possible_paths:
        if os.path.exists(p):
            found_path = p
            break

    if not found_path:
        raise HTTPException(status_code=404, detail="Default reference file 'Pay.xlsx' not found.")

    with open(found_path, "rb") as f:
        content = f.read()

    filename = os.path.basename(found_path)
    records, meta = parse_and_normalize_data(content, filename)
    dataset = replace_active_dataset(db, filename, meta["sheet_name"], records)

    return {
        "success": True,
        "message": f"Dashboard initialized from reference file {filename}",
        "dataset_id": dataset.id,
        "total_records": dataset.total_records,
        "total_invoice_value": dataset.total_invoice_value,
    }

def extract_filters(
    unit: Optional[str] = None,
    vendor_name: Optional[str] = None,
    bbu_number: Optional[str] = None,
    po_number: Optional[str] = None,
    invoice_number: Optional[str] = None,
    overall_status: Optional[str] = None,
    grn_status: Optional[str] = None,
    ssc_status: Optional[str] = None,
    payment_due_category: Optional[str] = None,
    is_non_billable: Optional[bool] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    if unit: filters["unit"] = unit
    if vendor_name: filters["vendor_name"] = vendor_name
    if bbu_number: filters["bbu_number"] = bbu_number
    if po_number: filters["po_number"] = po_number
    if invoice_number: filters["invoice_number"] = invoice_number
    if overall_status: filters["overall_status"] = overall_status
    if grn_status: filters["grn_status"] = grn_status
    if ssc_status: filters["ssc_status"] = ssc_status
    if payment_due_category: filters["payment_due_category"] = payment_due_category
    if is_non_billable is not None: filters["is_non_billable"] = is_non_billable
    if date_from: filters["date_from"] = date_from
    if date_to: filters["date_to"] = date_to
    return filters

@app.get("/api/kpis")
def get_kpis(
    unit: Optional[str] = None,
    vendor_name: Optional[str] = None,
    bbu_number: Optional[str] = None,
    po_number: Optional[str] = None,
    invoice_number: Optional[str] = None,
    overall_status: Optional[str] = None,
    grn_status: Optional[str] = None,
    ssc_status: Optional[str] = None,
    payment_due_category: Optional[str] = None,
    is_non_billable: Optional[bool] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
):
    active = get_active_dataset(db)
    if not active:
        return get_kpis_data(db, 0, {})
    active_id = getattr(active, "id")
    filters = extract_filters(
        unit, vendor_name, bbu_number, po_number, invoice_number,
        overall_status, grn_status, ssc_status, payment_due_category,
        is_non_billable, date_from, date_to
    )
    return get_kpis_data(db, active_id, filters)

@app.get("/api/charts")
def get_charts(
    unit: Optional[str] = None,
    vendor_name: Optional[str] = None,
    bbu_number: Optional[str] = None,
    po_number: Optional[str] = None,
    invoice_number: Optional[str] = None,
    overall_status: Optional[str] = None,
    grn_status: Optional[str] = None,
    ssc_status: Optional[str] = None,
    payment_due_category: Optional[str] = None,
    is_non_billable: Optional[bool] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
):
    active = get_active_dataset(db)
    if not active:
        return {
            "status_donut": [],
            "monthly_trend": [],
            "grn_progress": {"completed_count": 0, "pending_count": 0, "total_count": 0, "completion_pct": 0},
            "ssc_progress": [],
            "payment_due_aging": [],
            "top_vendors_by_pending_value": [],
            "top_vendors_by_pending_records": [],
            "vendor_status_breakdown": [],
        }
    filters = extract_filters(
        unit, vendor_name, bbu_number, po_number, invoice_number,
        overall_status, grn_status, ssc_status, payment_due_category,
        is_non_billable, date_from, date_to
    )
    active_id = getattr(active, "id")
    return get_charts_data(db, active_id, filters)

@app.get("/api/filters")
def get_filters(db: Session = Depends(get_db)):
    active = get_active_dataset(db)
    if not active:
        return {
            "units": [],
            "vendors": [],
            "bbus": [],
            "overall_statuses": [],
            "grn_statuses": [],
            "ssc_statuses": [],
            "payment_categories": [],
        }
    active_id = getattr(active, "id")
    return get_filter_options(db, active_id)

@app.get("/api/invoices")
def get_invoices(
    unit: Optional[str] = None,
    vendor_name: Optional[str] = None,
    bbu_number: Optional[str] = None,
    po_number: Optional[str] = None,
    invoice_number: Optional[str] = None,
    overall_status: Optional[str] = None,
    grn_status: Optional[str] = None,
    ssc_status: Optional[str] = None,
    payment_due_category: Optional[str] = None,
    is_non_billable: Optional[bool] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "id",
    sort_order: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    active = get_active_dataset(db)
    if not active:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    filters = extract_filters(
        unit, vendor_name, bbu_number, po_number, invoice_number,
        overall_status, grn_status, ssc_status, payment_due_category,
        is_non_billable, date_from, date_to
    )
    active_id = getattr(active, "id")
    items, total = get_invoices_paged(
        db, active_id, filters, search, sort_by, sort_order, page, page_size
    )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 1
    }

@app.get("/api/invoices/{invoice_id}")
def get_invoice_detail(invoice_id: int, db: Session = Depends(get_db)):
    inv = get_invoice_by_id(db, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice record not found")
    return inv

@app.get("/api/action-required")
def get_action_required(db: Session = Depends(get_db)):
    active = get_active_dataset(db)
    if not active:
        return []
    active_id = getattr(active, "id")
    return get_action_required_list(db, active_id)

@app.get("/api/data-quality")
def get_data_quality(db: Session = Depends(get_db)):
    active = get_active_dataset(db)
    if not active:
        return {
            "total_records": 0,
            "missing_invoice_number": 0,
            "missing_vendor": 0,
            "missing_po": 0,
            "missing_grn": 0,
            "missing_grn_date": 0,
            "missing_ssc_request": 0,
            "missing_invoice_date": 0,
            "missing_amount": 0,
            "invalid_dates": 0,
            "invalid_amounts": 0,
            "duplicate_records": 0,
            "affected_record_ids": {}
        }
    active_id = getattr(active, "id")
    return get_data_quality_report(db, active_id)

@app.get("/api/export")
def export_data(
    format: str = Query("csv", pattern="^(csv|excel)$"),
    scope: str = Query("all", pattern="^(all|filtered|action|overdue)$"),
    unit: Optional[str] = None,
    vendor_name: Optional[str] = None,
    overall_status: Optional[str] = None,
    grn_status: Optional[str] = None,
    ssc_status: Optional[str] = None,
    payment_due_category: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    active = get_active_dataset(db)
    if not active:
        raise HTTPException(status_code=400, detail="No active dataset to export.")

    filters = extract_filters(
        unit=unit, vendor_name=vendor_name,
        overall_status=overall_status, grn_status=grn_status,
        ssc_status=ssc_status, payment_due_category=payment_due_category
    )

    active_id = getattr(active, "id")
    if scope == "action":
        action_items = get_action_required_list(db, active_id)
        df = pd.DataFrame(action_items)
    elif scope == "overdue":
        filters["payment_due_category"] = "OVERDUE"
        items, _ = get_invoices_paged(db, active_id, filters, page=1, page_size=10000)
        df = pd.DataFrame(items)
    else:
        # All or filtered
        items, _ = get_invoices_paged(db, active_id, filters if scope == "filtered" else {}, search=search, page=1, page_size=20000)
        df = pd.DataFrame(items)

    # Drop internal technical columns for export
    for col in ["dataset_id", "is_duplicate"]:
        if col in df.columns:
            df = df.drop(columns=[col])

    if format == "csv":
        stream = io.StringIO()
        df.to_csv(stream, index=False)
        response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
        response.headers["Content-Disposition"] = f"attachment; filename=nabinagar_{scope}_export.csv"
        return response
    else:
        stream = io.BytesIO()
        with pd.ExcelWriter(stream, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Exported Data")
        stream.seek(0)
        response = StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response.headers["Content-Disposition"] = f"attachment; filename=nabinagar_{scope}_export.xlsx"
        return response

def get_frontend_dist_dir() -> Optional[str]:
    """Finds the built frontend production files in bundle or development workspace."""
    # Priority 1: Inside PyInstaller bundle (_MEIPASS/frontend_dist)
    if getattr(sys, "frozen", False):
        bundle_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
        dist_in_bundle = os.path.join(bundle_dir, "frontend_dist")
        if os.path.isdir(dist_in_bundle):
            return dist_in_bundle
        
        # Alongside executable
        app_dir = os.path.dirname(os.path.abspath(sys.executable))
        dist_next_to_exe = os.path.join(app_dir, "frontend_dist")
        if os.path.isdir(dist_next_to_exe):
            return dist_next_to_exe
        dist_folder = os.path.join(app_dir, "frontend", "dist")
        if os.path.isdir(dist_folder):
            return dist_folder

    # Priority 2: Development workspace
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dev_dist = os.path.abspath(os.path.join(base_dir, "..", "frontend", "dist"))
    if os.path.isdir(dev_dist):
        return dev_dist

    return None

dist_dir = get_frontend_dist_dir()
if dist_dir and os.path.isdir(dist_dir):
    spa_dir: str = dist_dir
    assets_dir = os.path.join(spa_dir, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Do not intercept API or documentation routes
        if full_path.startswith("api/") or full_path in ("docs", "openapi.json", "redoc"):
            raise HTTPException(status_code=404, detail="Not Found")
        target_file = os.path.join(spa_dir, full_path)
        if full_path and os.path.isfile(target_file):
            return FileResponse(target_file)
        index_file = os.path.join(spa_dir, "index.html")
        if os.path.isfile(index_file):
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail="Frontend index.html not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
