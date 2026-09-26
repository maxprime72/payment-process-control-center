import os
import sys
import datetime
from sqlalchemy import create_engine, func, or_, and_, desc, asc, event, text
from sqlalchemy.orm import sessionmaker, Session
from typing import Dict, List, Any, Optional, Tuple

from models import Base, DatasetMeta, Invoice
from services.status_engine import (
    process_single_record,
    generate_action_items,
    analyze_data_quality_issues,
    STATUS_COMPLETED,
    STATUS_IN_PROCESS,
    STATUS_PROCESSED,
    STATUS_UNPROCESSED,
    DUE_OVERDUE,
    DUE_COMPLETED,
    DUE_SOON,
    DUE_TODAY,
    DUE_NOT_DUE
)

def get_database_path() -> str:
    """Returns the portable database path, honoring frozen status, env vars, or development defaults."""
    env_path = os.environ.get("PAYBLE_DB_PATH")
    if env_path:
        os.makedirs(os.path.dirname(os.path.abspath(env_path)), exist_ok=True)
        return os.path.abspath(env_path)

    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(os.path.abspath(sys.executable))
        data_dir = os.path.join(app_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "nabinagar_pay.db")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    root_data_db = os.path.abspath(os.path.join(base_dir, "..", "..", "data", "nabinagar_pay.db"))
    if os.path.exists(root_data_db):
        return root_data_db

    backend_data_db = os.path.abspath(os.path.join(base_dir, "..", "data", "nabinagar_pay.db"))
    os.makedirs(os.path.dirname(backend_data_db), exist_ok=True)
    return backend_data_db

DB_PATH = get_database_path()
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30.0}
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def checkpoint_database():
    """Performs a WAL checkpoint to truncate WAL and integrate transactions into main DB file."""
    try:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE);"))
            conn.commit()
    except Exception:
        pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def replace_active_dataset(db: Session, filename: str, sheet_name: str, raw_records: List[Dict[str, Any]]) -> DatasetMeta:
    """
    Replaces the active dataset in the database.
    Marks old datasets inactive and bulk inserts newly processed records.
    """
    # Deactivate prior datasets
    db.query(DatasetMeta).update({DatasetMeta.is_active: False})

    # Create dataset entry
    dataset = DatasetMeta(
        filename=filename,
        sheet_name=sheet_name,
        uploaded_at=datetime.datetime.now(datetime.timezone.utc),
        total_records=len(raw_records),
        total_invoice_value=sum(r.get("gross_invoice_total", 0.0) for r in raw_records),
        total_amount_payable=sum(r.get("total_amount_payable", 0.0) for r in raw_records),
        is_active=True
    )
    db.add(dataset)
    db.flush()

    today = datetime.date.today()
    invoice_objects = []

    for r in raw_records:
        processed = process_single_record(r, reference_date=today)
        inv = Invoice(
            dataset_id=dataset.id,
            unit=processed.get("unit"),
            bbu_number=processed.get("bbu_number"),
            item_description=processed.get("item_description"),
            vendor_name=processed.get("vendor_name"),
            po_number=processed.get("po_number"),
            invoice_number=processed.get("invoice_number"),
            invoice_date=processed.get("invoice_date"),
            grn_number=processed.get("grn_number"),
            grn_date=processed.get("grn_date"),
            basic_amount=processed.get("basic_amount", 0.0),
            gross_invoice_total=processed.get("gross_invoice_total", 0.0),
            total_amount_payable=processed.get("total_amount_payable", 0.0),
            ssc_request_number=processed.get("ssc_request_number"),
            ssc_upload_date=processed.get("ssc_upload_date"),
            hard_copy_received_date=processed.get("hard_copy_received_date"),
            hard_copy_sent_date=processed.get("hard_copy_sent_date"),
            payment_due_days_raw=processed.get("payment_due_days_raw"),
            invoice_processing_status=processed.get("invoice_processing_status"),
            processed=processed.get("processed"),
            inprocess=processed.get("inprocess"),
            remark_closure_date=processed.get("remark_closure_date"),
            kz_number=processed.get("kz_number"),
            kz_date=processed.get("kz_date"),
            rt=processed.get("rt", 0.0),
            ld=processed.get("ld", 0.0),
            ka=processed.get("ka", 0.0),
            kd=processed.get("kd", 0.0),
            tds=processed.get("tds", 0.0),
            overall_status=processed.get("overall_status"),
            grn_status=processed.get("grn_status"),
            ssc_status=processed.get("ssc_status"),
            calculated_due_date=processed.get("calculated_due_date"),
            days_remaining=processed.get("days_remaining", 0),
            days_overdue=processed.get("days_overdue", 0),
            payment_due_category=processed.get("payment_due_category"),
            is_non_billable=processed.get("is_non_billable", False),
            is_duplicate=processed.get("is_duplicate", False),
        )
        invoice_objects.append(inv)

    db.bulk_save_objects(invoice_objects)
    db.commit()
    db.refresh(dataset)
    return dataset

def get_active_dataset(db: Session) -> Optional[DatasetMeta]:
    return db.query(DatasetMeta).filter(DatasetMeta.is_active == True).order_by(desc(DatasetMeta.id)).first()

def get_dataset_history(db: Session) -> List[Dict[str, Any]]:
    datasets = db.query(DatasetMeta).order_by(desc(DatasetMeta.uploaded_at)).all()
    history = []
    for d in datasets:
        up_at = getattr(d, "uploaded_at", None)
        history.append({
            "id": getattr(d, "id"),
            "filename": getattr(d, "filename"),
            "sheet_name": getattr(d, "sheet_name"),
            "uploaded_at": up_at.strftime("%Y-%m-%d %H:%M:%S") if up_at is not None else "",
            "total_records": getattr(d, "total_records", 0),
            "total_invoice_value": getattr(d, "total_invoice_value", 0.0),
            "total_amount_payable": getattr(d, "total_amount_payable", 0.0),
            "is_active": getattr(d, "is_active", False)
        })
    return history

def apply_invoice_filters(query, filters: Dict[str, Any]):
    if not filters:
        return query

    if filters.get("unit"):
        query = query.filter(Invoice.unit == filters["unit"])
    if filters.get("vendor_name"):
        query = query.filter(Invoice.vendor_name == filters["vendor_name"])
    if filters.get("bbu_number"):
        query = query.filter(Invoice.bbu_number == filters["bbu_number"])
    if filters.get("po_number"):
        query = query.filter(Invoice.po_number == filters["po_number"])
    if filters.get("invoice_number"):
        query = query.filter(Invoice.invoice_number == filters["invoice_number"])
    if filters.get("overall_status"):
        query = query.filter(Invoice.overall_status == filters["overall_status"])
    if filters.get("grn_status"):
        query = query.filter(Invoice.grn_status == filters["grn_status"])
    if filters.get("ssc_status"):
        query = query.filter(Invoice.ssc_status == filters["ssc_status"])
    if filters.get("payment_due_category"):
        query = query.filter(Invoice.payment_due_category == filters["payment_due_category"])
    if filters.get("is_non_billable") is not None:
        query = query.filter(Invoice.is_non_billable == bool(filters["is_non_billable"]))
    if filters.get("date_from"):
        query = query.filter(Invoice.invoice_date >= filters["date_from"])
    if filters.get("date_to"):
        query = query.filter(Invoice.invoice_date <= filters["date_to"])

    return query

def get_kpis_data(db: Session, dataset_id: int, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base_query = db.query(Invoice).filter(Invoice.dataset_id == dataset_id)
    base_query = apply_invoice_filters(base_query, filters or {})

    invoices = base_query.all()
    total_records = len(invoices)

    if total_records == 0:
        return {
            "total_records": 0,
            "total_invoice_value": 0.0,
            "total_basic_amount": 0.0,
            "total_amount_payable": 0.0,
            "completed_count": 0,
            "completed_value": 0.0,
            "completed_percentage": 0.0,
            "in_process_count": 0,
            "in_process_value": 0.0,
            "in_process_percentage": 0.0,
            "processed_count": 0,
            "processed_value": 0.0,
            "processed_percentage": 0.0,
            "unprocessed_count": 0,
            "unprocessed_value": 0.0,
            "unprocessed_percentage": 0.0,
            "incomplete_count": 0,
            "incomplete_value": 0.0,
            "incomplete_percentage": 0.0,
            "billable_count": 0,
            "billable_completed_count": 0,
            "billable_completion_pct": 0.0,
            "non_billable_count": 0,
            "non_billable_completed_count": 0,
            "non_billable_completion_pct": 0.0,
            "summary_sentence": "No data available in current view."
        }

    total_gross = sum(i.gross_invoice_total or 0.0 for i in invoices)
    total_basic = sum(i.basic_amount or 0.0 for i in invoices)
    total_payable = sum(i.total_amount_payable or 0.0 for i in invoices)

    completed = [i for i in invoices if i.overall_status == STATUS_COMPLETED]
    in_process = [i for i in invoices if i.overall_status == STATUS_IN_PROCESS]
    processed = [i for i in invoices if i.overall_status == STATUS_PROCESSED]
    unprocessed = [i for i in invoices if i.overall_status == STATUS_UNPROCESSED]

    completed_count = len(completed)
    completed_val = sum(i.gross_invoice_total or 0.0 for i in completed)
    completed_pct = round((completed_count / total_records) * 100, 1)

    in_process_count = len(in_process)
    in_process_val = sum(i.gross_invoice_total or 0.0 for i in in_process)
    in_process_pct = round((in_process_count / total_records) * 100, 1)

    processed_count = len(processed)
    processed_val = sum(i.gross_invoice_total or 0.0 for i in processed)
    processed_pct = round((processed_count / total_records) * 100, 1)

    unprocessed_count = len(unprocessed)
    unprocessed_val = sum(i.gross_invoice_total or 0.0 for i in unprocessed)
    unprocessed_pct = round((unprocessed_count / total_records) * 100, 1)

    incomplete_count = total_records - completed_count
    incomplete_val = total_gross - completed_val
    incomplete_pct = round((incomplete_count / total_records) * 100, 1)

    billable = [i for i in invoices if not i.is_non_billable]
    non_billable = [i for i in invoices if i.is_non_billable]

    billable_count = len(billable)
    billable_comp = sum(1 for i in billable if i.overall_status == STATUS_COMPLETED)
    billable_pct = round((billable_comp / billable_count) * 100, 1) if billable_count else 0.0

    non_billable_count = len(non_billable)
    non_billable_comp = sum(1 for i in non_billable if i.overall_status == STATUS_COMPLETED)
    non_billable_pct = round((non_billable_comp / non_billable_count) * 100, 1) if non_billable_count else 0.0

    summary_sentence = (
        f"{completed_pct}% of the total payment-processing workload is completed. "
        f"{in_process_count} records are currently in process, "
        f"{processed_count} records have been processed but are awaiting final completion, and "
        f"{unprocessed_count} records remain unprocessed."
    )

    return {
        "total_records": total_records,
        "total_invoice_value": round(total_gross, 2),
        "total_basic_amount": round(total_basic, 2),
        "total_amount_payable": round(total_payable, 2),
        "completed_count": completed_count,
        "completed_value": round(completed_val, 2),
        "completed_percentage": completed_pct,
        "in_process_count": in_process_count,
        "in_process_value": round(in_process_val, 2),
        "in_process_percentage": in_process_pct,
        "processed_count": processed_count,
        "processed_value": round(processed_val, 2),
        "processed_percentage": processed_pct,
        "unprocessed_count": unprocessed_count,
        "unprocessed_value": round(unprocessed_val, 2),
        "unprocessed_percentage": unprocessed_pct,
        "incomplete_count": incomplete_count,
        "incomplete_value": round(incomplete_val, 2),
        "incomplete_percentage": incomplete_pct,
        "billable_count": billable_count,
        "billable_completed_count": billable_comp,
        "billable_completion_pct": billable_pct,
        "non_billable_count": non_billable_count,
        "non_billable_completed_count": non_billable_comp,
        "non_billable_completion_pct": non_billable_pct,
        "summary_sentence": summary_sentence,
    }

def get_charts_data(db: Session, dataset_id: int, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base_query = db.query(Invoice).filter(Invoice.dataset_id == dataset_id)
    base_query = apply_invoice_filters(base_query, filters or {})
    invoices = base_query.all()

    # 1. Donut: Payment Processing Status
    status_counts: Dict[str, Dict[str, Any]] = {
        STATUS_COMPLETED: {"count": 0, "value": 0.0, "color": "#10b981"},
        STATUS_IN_PROCESS: {"count": 0, "value": 0.0, "color": "#f59e0b"},
        STATUS_PROCESSED: {"count": 0, "value": 0.0, "color": "#3b82f6"},
        STATUS_UNPROCESSED: {"count": 0, "value": 0.0, "color": "#f43f5e"},
    }

    # 2. Monthly Trend
    monthly_data: Dict[str, Dict[str, Any]] = {}

    # 3. GRN
    grn_completed_count = 0
    grn_completed_val = 0.0
    grn_pending_count = 0
    grn_pending_val = 0.0

    # 4. SSC stages
    ssc_stages = {
        "COMPLETED": 0,
        "SENT TO F&A": 0,
        "HARD COPY RECEIVED": 0,
        "UPLOADED IN SSC": 0,
        "NOT SUBMITTED": 0,
    }

    # 5. Payment Due Aging
    due_buckets = {
        DUE_NOT_DUE: {"count": 0, "value": 0.0},
        DUE_SOON: {"count": 0, "value": 0.0},
        DUE_TODAY: {"count": 0, "value": 0.0},
        DUE_OVERDUE: {"count": 0, "value": 0.0},
        DUE_COMPLETED: {"count": 0, "value": 0.0},
    }

    # 6 & 7. Vendor metrics
    vendor_stats: Dict[str, Dict[str, Any]] = {}

    for inv in invoices:
        gross = inv.gross_invoice_total or 0.0
        st = inv.overall_status
        if st in status_counts:
            status_counts[st]["count"] += 1
            status_counts[st]["value"] += gross

        # Monthly
        inv_dt = inv.invoice_date
        if inv_dt and len(inv_dt) >= 7:
            ym = inv_dt[:7]
            if ym not in monthly_data:
                monthly_data[ym] = {
                    "year_month": ym,
                    "count": 0,
                    "value": 0.0,
                    "completed_count": 0,
                    "in_process_count": 0,
                    "processed_count": 0,
                    "unprocessed_count": 0,
                }
            monthly_data[ym]["count"] += 1
            monthly_data[ym]["value"] += gross
            if st == STATUS_COMPLETED:
                monthly_data[ym]["completed_count"] += 1
            elif st == STATUS_IN_PROCESS:
                monthly_data[ym]["in_process_count"] += 1
            elif st == STATUS_PROCESSED:
                monthly_data[ym]["processed_count"] += 1
            else:
                monthly_data[ym]["unprocessed_count"] += 1

        # GRN
        if inv.grn_status == "COMPLETED":
            grn_completed_count += 1
            grn_completed_val += gross
        else:
            grn_pending_count += 1
            grn_pending_val += gross

        # SSC
        ssc_st = inv.ssc_status
        if ssc_st in ssc_stages:
            ssc_stages[ssc_st] += 1

        # Due aging
        cat = inv.payment_due_category
        if cat in due_buckets:
            due_buckets[cat]["count"] += 1
            due_buckets[cat]["value"] += gross

        # Vendor
        v = inv.vendor_name or "Unknown Vendor"
        if v not in vendor_stats:
            vendor_stats[v] = {
                "vendor_name": v,
                "total_records": 0,
                "total_value": 0.0,
                "completed_count": 0,
                "in_process_count": 0,
                "processed_count": 0,
                "unprocessed_count": 0,
                "pending_count": 0,
                "pending_value": 0.0,
                "overdue_count": 0,
                "overdue_value": 0.0,
                "completion_pct": 0.0,
            }
        vendor_stats[v]["total_records"] += 1
        vendor_stats[v]["total_value"] += gross
        if st == STATUS_COMPLETED:
            vendor_stats[v]["completed_count"] += 1
        else:
            vendor_stats[v]["pending_count"] += 1
            vendor_stats[v]["pending_value"] += gross
            if st == STATUS_IN_PROCESS:
                vendor_stats[v]["in_process_count"] += 1
            elif st == STATUS_PROCESSED:
                vendor_stats[v]["processed_count"] += 1
            else:
                vendor_stats[v]["unprocessed_count"] += 1

        if cat == DUE_OVERDUE and st != STATUS_COMPLETED:
            vendor_stats[v]["overdue_count"] += 1
            vendor_stats[v]["overdue_value"] += gross

    # Format donut
    status_donut = [
        {"name": k, "count": int(v["count"]), "value": round(float(v["value"]), 2), "color": str(v["color"])}
        for k, v in status_counts.items()
    ]

    # Format monthly
    monthly_trend = []
    for ym in sorted(monthly_data.keys()):
        item = monthly_data[ym]
        c = item["count"]
        comp = item["completed_count"]
        pct = round((comp / c) * 100, 1) if c else 0.0
        # Format "YYYY-MM" to readable "Mon YYYY"
        try:
            m_dt = datetime.datetime.strptime(ym, "%Y-%m")
            readable_m = m_dt.strftime("%b %Y")
        except Exception:
            readable_m = ym
        monthly_trend.append({
            "month": readable_m,
            "year_month": ym,
            "count": item["count"],
            "value": round(item["value"], 2),
            "completed_count": item["completed_count"],
            "in_process_count": item["in_process_count"],
            "processed_count": item["processed_count"],
            "unprocessed_count": item["unprocessed_count"],
            "completion_pct": pct,
        })

    # Format GRN
    grn_progress = {
        "completed_count": grn_completed_count,
        "completed_value": round(grn_completed_val, 2),
        "pending_count": grn_pending_count,
        "pending_value": round(grn_pending_val, 2),
        "total_count": grn_completed_count + grn_pending_count,
        "completion_pct": round((grn_completed_count / (grn_completed_count + grn_pending_count) * 100), 1) if (grn_completed_count + grn_pending_count) else 0.0
    }

    # Format SSC
    ssc_progress = [
        {"stage": k, "count": v} for k, v in ssc_stages.items()
    ]

    # Format Payment Due
    payment_due_aging = [
        {"category": k, "count": v["count"], "value": round(v["value"], 2)}
        for k, v in due_buckets.items()
    ]

    # Vendor items
    all_vendors = list(vendor_stats.values())
    for v in all_vendors:
        tot = v["total_records"]
        comp = v["completed_count"]
        v["completion_pct"] = round((comp / tot) * 100, 1) if tot else 0.0
        v["total_value"] = round(v["total_value"], 2)
        v["pending_value"] = round(v["pending_value"], 2)
        v["overdue_value"] = round(v["overdue_value"], 2)

    top_by_pending_val = sorted(all_vendors, key=lambda x: x["pending_value"], reverse=True)[:10]
    top_by_pending_rec = sorted(all_vendors, key=lambda x: x["pending_count"], reverse=True)[:10]
    top_by_records = sorted(all_vendors, key=lambda x: x["total_records"], reverse=True)[:15]

    return {
        "status_donut": status_donut,
        "monthly_trend": monthly_trend,
        "grn_progress": grn_progress,
        "ssc_progress": ssc_progress,
        "payment_due_aging": payment_due_aging,
        "top_vendors_by_pending_value": top_by_pending_val,
        "top_vendors_by_pending_records": top_by_pending_rec,
        "vendor_status_breakdown": top_by_records,
    }

def get_invoices_paged(
    db: Session,
    dataset_id: int,
    filters: Optional[Dict[str, Any]] = None,
    search: Optional[str] = None,
    sort_by: str = "id",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 50
) -> Tuple[List[Dict[str, Any]], int]:
    query = db.query(Invoice).filter(Invoice.dataset_id == dataset_id)
    query = apply_invoice_filters(query, filters or {})

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Invoice.invoice_number.ilike(term),
                Invoice.po_number.ilike(term),
                Invoice.vendor_name.ilike(term),
                Invoice.grn_number.ilike(term),
                Invoice.ssc_request_number.ilike(term),
                Invoice.bbu_number.ilike(term),
            )
        )

    total_count = query.count()

    # Sorting
    col_attr = getattr(Invoice, sort_by, Invoice.id)
    if sort_order.lower() == "asc":
        query = query.order_by(asc(col_attr))
    else:
        query = query.order_by(desc(col_attr))

    offset = (page - 1) * page_size
    records = query.offset(offset).limit(page_size).all()

    items = [
        {
            "id": r.id,
            "unit": r.unit,
            "bbu_number": r.bbu_number,
            "item_description": r.item_description,
            "vendor_name": r.vendor_name,
            "po_number": r.po_number,
            "invoice_number": r.invoice_number,
            "invoice_date": r.invoice_date,
            "grn_number": r.grn_number,
            "grn_date": r.grn_date,
            "basic_amount": r.basic_amount,
            "gross_invoice_total": r.gross_invoice_total,
            "total_amount_payable": r.total_amount_payable,
            "ssc_request_number": r.ssc_request_number,
            "ssc_upload_date": r.ssc_upload_date,
            "hard_copy_received_date": r.hard_copy_received_date,
            "hard_copy_sent_date": r.hard_copy_sent_date,
            "payment_due_days_raw": r.payment_due_days_raw,
            "invoice_processing_status": r.invoice_processing_status,
            "processed": r.processed,
            "inprocess": r.inprocess,
            "remark_closure_date": r.remark_closure_date,
            "kz_number": r.kz_number,
            "kz_date": r.kz_date,
            "rt": r.rt,
            "ld": r.ld,
            "ka": r.ka,
            "kd": r.kd,
            "tds": r.tds,
            "overall_status": r.overall_status,
            "grn_status": r.grn_status,
            "ssc_status": r.ssc_status,
            "calculated_due_date": r.calculated_due_date,
            "days_remaining": r.days_remaining,
            "days_overdue": r.days_overdue,
            "payment_due_category": r.payment_due_category,
            "is_non_billable": r.is_non_billable,
            "is_duplicate": r.is_duplicate,
        }
        for r in records
    ]

    return items, total_count

def get_invoice_by_id(db: Session, invoice_id: int) -> Optional[Dict[str, Any]]:
    r = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not r:
        return None
    return {
        "id": r.id,
        "unit": r.unit,
        "bbu_number": r.bbu_number,
        "item_description": r.item_description,
        "vendor_name": r.vendor_name,
        "po_number": r.po_number,
        "invoice_number": r.invoice_number,
        "invoice_date": r.invoice_date,
        "grn_number": r.grn_number,
        "grn_date": r.grn_date,
        "basic_amount": r.basic_amount,
        "gross_invoice_total": r.gross_invoice_total,
        "total_amount_payable": r.total_amount_payable,
        "ssc_request_number": r.ssc_request_number,
        "ssc_upload_date": r.ssc_upload_date,
        "hard_copy_received_date": r.hard_copy_received_date,
        "hard_copy_sent_date": r.hard_copy_sent_date,
        "payment_due_days_raw": r.payment_due_days_raw,
        "invoice_processing_status": r.invoice_processing_status,
        "processed": r.processed,
        "inprocess": r.inprocess,
        "remark_closure_date": r.remark_closure_date,
        "kz_number": r.kz_number,
        "kz_date": r.kz_date,
        "rt": r.rt,
        "ld": r.ld,
        "ka": r.ka,
        "kd": r.kd,
        "tds": r.tds,
        "overall_status": r.overall_status,
        "grn_status": r.grn_status,
        "ssc_status": r.ssc_status,
        "calculated_due_date": r.calculated_due_date,
        "days_remaining": r.days_remaining,
        "days_overdue": r.days_overdue,
        "payment_due_category": r.payment_due_category,
        "is_non_billable": r.is_non_billable,
        "is_duplicate": r.is_duplicate,
    }

def get_filter_options(db: Session, dataset_id: int) -> Dict[str, List[Any]]:
    units = [u[0] for u in db.query(Invoice.unit).filter(Invoice.dataset_id == dataset_id, Invoice.unit.isnot(None)).distinct().all()]
    vendors = [v[0] for v in db.query(Invoice.vendor_name).filter(Invoice.dataset_id == dataset_id, Invoice.vendor_name.isnot(None)).distinct().order_by(Invoice.vendor_name).all()]
    bbus = [b[0] for b in db.query(Invoice.bbu_number).filter(Invoice.dataset_id == dataset_id, Invoice.bbu_number.isnot(None)).distinct().order_by(Invoice.bbu_number).all()]
    overall_statuses = [STATUS_COMPLETED, STATUS_IN_PROCESS, STATUS_PROCESSED, STATUS_UNPROCESSED]
    grn_statuses = ["COMPLETED", "PENDING"]
    ssc_statuses = ["COMPLETED", "SENT TO F&A", "HARD COPY RECEIVED", "UPLOADED IN SSC", "NOT SUBMITTED"]
    payment_categories = [DUE_NOT_DUE, DUE_SOON, DUE_TODAY, DUE_OVERDUE, DUE_COMPLETED]

    return {
        "units": sorted(units),
        "vendors": vendors,
        "bbus": bbus,
        "overall_statuses": overall_statuses,
        "grn_statuses": grn_statuses,
        "ssc_statuses": ssc_statuses,
        "payment_categories": payment_categories,
    }

def get_action_required_list(db: Session, dataset_id: int) -> List[Dict[str, Any]]:
    invoices = db.query(Invoice).filter(Invoice.dataset_id == dataset_id).all()
    records = [
        {
            "id": r.id,
            "invoice_number": r.invoice_number,
            "vendor_name": r.vendor_name,
            "po_number": r.po_number,
            "invoice_date": r.invoice_date,
            "gross_invoice_total": r.gross_invoice_total,
            "overall_status": r.overall_status,
            "grn_status": r.grn_status,
            "ssc_status": r.ssc_status,
            "payment_due_category": r.payment_due_category,
            "calculated_due_date": r.calculated_due_date,
            "days_overdue": r.days_overdue,
        }
        for r in invoices
    ]
    return generate_action_items(records)

def get_data_quality_report(db: Session, dataset_id: int) -> Dict[str, Any]:
    invoices = db.query(Invoice).filter(Invoice.dataset_id == dataset_id).all()
    records = [
        {
            "id": r.id,
            "invoice_number": r.invoice_number,
            "vendor_name": r.vendor_name,
            "po_number": r.po_number,
            "invoice_date": r.invoice_date,
            "grn_number": r.grn_number,
            "grn_date": r.grn_date,
            "ssc_request_number": r.ssc_request_number,
            "gross_invoice_total": r.gross_invoice_total,
            "is_duplicate": r.is_duplicate,
        }
        for r in invoices
    ]
    return analyze_data_quality_issues(records)
