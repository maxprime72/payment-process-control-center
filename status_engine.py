import re
import datetime
from typing import Dict, List, Any, Optional, Tuple

STATUS_COMPLETED = "COMPLETED"
STATUS_IN_PROCESS = "IN PROCESS"
STATUS_PROCESSED = "PROCESSED / PENDING FINAL COMPLETION"
STATUS_UNPROCESSED = "UNPROCESSED"

DUE_NOT_DUE = "NOT DUE"
DUE_SOON = "DUE SOON"
DUE_TODAY = "DUE TODAY"
DUE_OVERDUE = "OVERDUE"
DUE_COMPLETED = "COMPLETED"

def compute_overall_status(row: Dict[str, Any]) -> str:
    """
    Centralized status determination:
    1. COMPLETED: If Invoice Processing status = COMPLETED (case-insensitive)
    2. IN PROCESS: If not completed and Inprocess = 1
    3. PROCESSED / PENDING FINAL COMPLETION: If not completed and Processed = 1
    4. UNPROCESSED: Otherwise
    """
    proc_status = str(row.get("invoice_processing_status") or "").strip().upper()
    if proc_status == "COMPLETED":
        return STATUS_COMPLETED

    in_proc = row.get("inprocess")
    if in_proc is not None:
        try:
            if float(in_proc) == 1.0 or str(in_proc).strip() in ["1", "1.0"]:
                return STATUS_IN_PROCESS
        except (ValueError, TypeError):
            pass

    proc = row.get("processed")
    if proc is not None:
        try:
            if float(proc) == 1.0 or str(proc).strip() in ["1", "1.0"]:
                return STATUS_PROCESSED
        except (ValueError, TypeError):
            pass

    return STATUS_UNPROCESSED

def compute_grn_status(grn_number: Optional[str]) -> str:
    """GRN Status: COMPLETED if GRN No is present, else PENDING."""
    if grn_number and grn_number.strip():
        return "COMPLETED"
    return "PENDING"

def compute_ssc_status(row: Dict[str, Any], overall_status: str) -> str:
    """
    SSC Stages:
    NOT SUBMITTED -> UPLOADED IN SSC -> HARD COPY RECEIVED -> SENT TO F&A -> COMPLETED
    """
    if overall_status == STATUS_COMPLETED:
        return "COMPLETED"

    if row.get("hard_copy_sent_date"):
        return "SENT TO F&A"
    if row.get("hard_copy_received_date"):
        return "HARD COPY RECEIVED"
    if row.get("ssc_upload_date") or row.get("ssc_request_number"):
        return "UPLOADED IN SSC"

    return "NOT SUBMITTED"

def compute_due_date_and_aging(
    invoice_date_str: Optional[str],
    payment_due_days_raw: Optional[str],
    overall_status: str,
    reference_date: Optional[datetime.date] = None
) -> Tuple[Optional[str], int, int, str]:
    """
    Calculates:
    - calculated_due_date (YYYY-MM-DD)
    - days_remaining
    - days_overdue
    - payment_due_category (NOT DUE, DUE SOON, DUE TODAY, OVERDUE, COMPLETED)
    """
    today = reference_date or datetime.date.today()
    calculated_due_date: Optional[datetime.date] = None

    # Check if payment_due_days_raw is a date string
    if payment_due_days_raw:
        raw_str = payment_due_days_raw.strip()
        # Check standard date formats like YYYY-MM-DD or DD-MM-YYYY
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"]:
            try:
                calculated_due_date = datetime.datetime.strptime(raw_str.split()[0], fmt).date()
                break
            except Exception:
                pass

        # If not a parsed date, check if numeric days or Excel serial
        if not calculated_due_date:
            try:
                num = float(raw_str)
                if num > 30000:  # Excel serial date (e.g. 46143)
                    calculated_due_date = (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(num)))
                elif invoice_date_str:  # Days offset from invoice date
                    inv_dt = datetime.datetime.strptime(invoice_date_str, "%Y-%m-%d").date()
                    calculated_due_date = inv_dt + datetime.timedelta(days=int(num))
            except Exception:
                pass

    # Fallback if no payment_due_days_raw but invoice_date exists (default 30 days)
    if not calculated_due_date and invoice_date_str:
        try:
            inv_dt = datetime.datetime.strptime(invoice_date_str, "%Y-%m-%d").date()
            calculated_due_date = inv_dt + datetime.timedelta(days=30)
        except Exception:
            pass

    if not calculated_due_date:
        cat = DUE_COMPLETED if overall_status == STATUS_COMPLETED else DUE_NOT_DUE
        return None, 0, 0, cat

    due_str = calculated_due_date.strftime("%Y-%m-%d")
    diff_days = (calculated_due_date - today).days

    if overall_status == STATUS_COMPLETED:
        return due_str, max(0, diff_days), 0, DUE_COMPLETED

    if diff_days < 0:
        days_overdue = abs(diff_days)
        return due_str, 0, days_overdue, DUE_OVERDUE
    elif diff_days == 0:
        return due_str, 0, 0, DUE_TODAY
    elif diff_days <= 7:
        return due_str, diff_days, 0, DUE_SOON
    else:
        return due_str, diff_days, 0, DUE_NOT_DUE

def process_single_record(record: Dict[str, Any], reference_date: Optional[datetime.date] = None) -> Dict[str, Any]:
    """Applies all business logic to a single record dict."""
    rec = dict(record)

    overall = compute_overall_status(rec)
    rec["overall_status"] = overall

    rec["grn_status"] = compute_grn_status(rec.get("grn_number"))
    rec["ssc_status"] = compute_ssc_status(rec, overall)

    due_date, remaining, overdue, category = compute_due_date_and_aging(
        rec.get("invoice_date"),
        rec.get("payment_due_days_raw"),
        overall,
        reference_date
    )
    rec["calculated_due_date"] = due_date
    rec["days_remaining"] = remaining
    rec["days_overdue"] = overdue
    rec["payment_due_category"] = category

    return rec

def generate_action_items(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Identifies actionable exceptions sorted by severity."""
    actions = []

    for r in records:
        rec_id = r.get("id") or 0
        overall = r.get("overall_status")
        gross = r.get("gross_invoice_total") or 0.0
        overdue_days = r.get("days_overdue") or 0
        cat = r.get("payment_due_category")
        grn_st = r.get("grn_status")
        ssc_st = r.get("ssc_status")

        # 1. Missing Critical Data
        missing = []
        if not r.get("invoice_number"):
            missing.append("Invoice No.")
        if not r.get("vendor_name"):
            missing.append("Vendor")
        if not r.get("po_number"):
            missing.append("PO No.")
        if not r.get("invoice_date"):
            missing.append("Invoice Date")
        if gross <= 0:
            missing.append("Amount")

        if missing:
            actions.append({
                "id": rec_id,
                "invoice_number": r.get("invoice_number"),
                "vendor_name": r.get("vendor_name"),
                "po_number": r.get("po_number"),
                "invoice_date": r.get("invoice_date"),
                "gross_invoice_total": gross,
                "overall_status": overall,
                "grn_status": grn_st,
                "ssc_status": ssc_st,
                "payment_due_category": cat,
                "calculated_due_date": r.get("calculated_due_date"),
                "days_overdue": overdue_days,
                "priority": "HIGH",
                "issue_type": "Data Incomplete",
                "issue_description": f"Missing critical fields: {', '.join(missing)}",
            })
            continue

        # 2. Payment Overdue (Only if not completed)
        if overall != STATUS_COMPLETED and cat == DUE_OVERDUE:
            prio = "CRITICAL" if (overdue_days > 30 or gross > 1000000) else "HIGH"
            actions.append({
                "id": rec_id,
                "invoice_number": r.get("invoice_number"),
                "vendor_name": r.get("vendor_name"),
                "po_number": r.get("po_number"),
                "invoice_date": r.get("invoice_date"),
                "gross_invoice_total": gross,
                "overall_status": overall,
                "grn_status": grn_st,
                "ssc_status": ssc_st,
                "payment_due_category": cat,
                "calculated_due_date": r.get("calculated_due_date"),
                "days_overdue": overdue_days,
                "priority": prio,
                "issue_type": "Payment Overdue",
                "issue_description": f"Payment is {overdue_days} days overdue (Due: {r.get('calculated_due_date')})",
            })
            continue

        # 3. GRN Pending
        if grn_st == "PENDING" and overall != STATUS_COMPLETED:
            actions.append({
                "id": rec_id,
                "invoice_number": r.get("invoice_number"),
                "vendor_name": r.get("vendor_name"),
                "po_number": r.get("po_number"),
                "invoice_date": r.get("invoice_date"),
                "gross_invoice_total": gross,
                "overall_status": overall,
                "grn_status": grn_st,
                "ssc_status": ssc_st,
                "payment_due_category": cat,
                "calculated_due_date": r.get("calculated_due_date"),
                "days_overdue": overdue_days,
                "priority": "HIGH",
                "issue_type": "GRN Pending",
                "issue_description": "GRN has not been created for this invoice",
            })
            continue

        # 4. SSC Pending (GRN complete but SSC not submitted or only uploaded)
        if grn_st == "COMPLETED" and ssc_st in ["NOT SUBMITTED", "UPLOADED IN SSC"] and overall != STATUS_COMPLETED:
            actions.append({
                "id": rec_id,
                "invoice_number": r.get("invoice_number"),
                "vendor_name": r.get("vendor_name"),
                "po_number": r.get("po_number"),
                "invoice_date": r.get("invoice_date"),
                "gross_invoice_total": gross,
                "overall_status": overall,
                "grn_status": grn_st,
                "ssc_status": ssc_st,
                "payment_due_category": cat,
                "calculated_due_date": r.get("calculated_due_date"),
                "days_overdue": overdue_days,
                "priority": "MEDIUM",
                "issue_type": "SSC Submission Pending",
                "issue_description": f"GRN completed; SSC status is {ssc_st}",
            })
            continue

        # 5. Unprocessed Record
        if overall == STATUS_UNPROCESSED:
            actions.append({
                "id": rec_id,
                "invoice_number": r.get("invoice_number"),
                "vendor_name": r.get("vendor_name"),
                "po_number": r.get("po_number"),
                "invoice_date": r.get("invoice_date"),
                "gross_invoice_total": gross,
                "overall_status": overall,
                "grn_status": grn_st,
                "ssc_status": ssc_st,
                "payment_due_category": cat,
                "calculated_due_date": r.get("calculated_due_date"),
                "days_overdue": overdue_days,
                "priority": "LOW",
                "issue_type": "Unprocessed Workload",
                "issue_description": "Record has not entered Inprocess or Processed state",
            })

    # Sort: CRITICAL first, then HIGH, then MEDIUM, then LOW
    priority_order: Dict[str, int] = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    actions.sort(
        key=lambda x: (
            priority_order.get(str(x.get("priority", "")), 9),
            -float(x.get("gross_invoice_total") or 0.0),
        )
    )
    return actions

def analyze_data_quality_issues(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Scans records for data quality defects and tracks affected IDs."""
    issues = {
        "total_records": len(records),
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
        "affected_record_ids": {
            "missing_invoice_number": [],
            "missing_vendor": [],
            "missing_po": [],
            "missing_grn": [],
            "missing_grn_date": [],
            "missing_ssc_request": [],
            "missing_invoice_date": [],
            "missing_amount": [],
            "invalid_dates": [],
            "invalid_amounts": [],
            "duplicate_records": [],
        }
    }

    for r in records:
        r_id = r.get("id") or 0

        if not r.get("invoice_number"):
            issues["missing_invoice_number"] += 1
            issues["affected_record_ids"]["missing_invoice_number"].append(r_id)

        if not r.get("vendor_name"):
            issues["missing_vendor"] += 1
            issues["affected_record_ids"]["missing_vendor"].append(r_id)

        if not r.get("po_number"):
            issues["missing_po"] += 1
            issues["affected_record_ids"]["missing_po"].append(r_id)

        if not r.get("grn_number"):
            issues["missing_grn"] += 1
            issues["affected_record_ids"]["missing_grn"].append(r_id)

        if not r.get("grn_date"):
            issues["missing_grn_date"] += 1
            issues["affected_record_ids"]["missing_grn_date"].append(r_id)

        if not r.get("ssc_request_number"):
            issues["missing_ssc_request"] += 1
            issues["affected_record_ids"]["missing_ssc_request"].append(r_id)

        if not r.get("invoice_date"):
            issues["missing_invoice_date"] += 1
            issues["affected_record_ids"]["missing_invoice_date"].append(r_id)

        gross = r.get("gross_invoice_total")
        if gross is None or gross <= 0:
            issues["missing_amount"] += 1
            issues["affected_record_ids"]["missing_amount"].append(r_id)

        if r.get("is_duplicate"):
            issues["duplicate_records"] += 1
            issues["affected_record_ids"]["duplicate_records"].append(r_id)

    return issues
