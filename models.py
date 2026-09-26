from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import declarative_base, relationship
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

Base = declarative_base()

class DatasetMeta(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    sheet_name = Column(String(100), nullable=False)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    total_records = Column(Integer, default=0)
    total_invoice_value = Column(Float, default=0.0)
    total_amount_payable = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)

    invoices = relationship("Invoice", back_populates="dataset", cascade="all, delete-orphan")


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)

    # Core Identification
    unit = Column(String(100), nullable=True, index=True)
    bbu_number = Column(String(150), nullable=True, index=True)
    item_description = Column(Text, nullable=True)

    # Vendor & PO
    vendor_name = Column(String(255), nullable=True, index=True)
    po_number = Column(String(100), nullable=True, index=True)

    # Invoice
    invoice_number = Column(String(100), nullable=True, index=True)
    invoice_date = Column(String(20), nullable=True, index=True)  # YYYY-MM-DD

    # GRN
    grn_number = Column(String(100), nullable=True, index=True)
    grn_date = Column(String(20), nullable=True)

    # Financial
    basic_amount = Column(Float, default=0.0)
    gross_invoice_total = Column(Float, default=0.0)
    total_amount_payable = Column(Float, default=0.0)

    # SSC
    ssc_request_number = Column(String(100), nullable=True, index=True)
    ssc_upload_date = Column(String(20), nullable=True)
    hard_copy_received_date = Column(String(20), nullable=True)
    hard_copy_sent_date = Column(String(20), nullable=True)

    # Payment & Processing Raw
    payment_due_days_raw = Column(String(100), nullable=True)
    invoice_processing_status = Column(String(100), nullable=True)
    processed = Column(Float, nullable=True)
    inprocess = Column(Float, nullable=True)

    # Financial deductions / adjustments
    remark_closure_date = Column(String(20), nullable=True)
    kz_number = Column(String(100), nullable=True)
    kz_date = Column(String(20), nullable=True)
    rt = Column(Float, default=0.0)
    ld = Column(Float, default=0.0)
    ka = Column(Float, default=0.0)
    kd = Column(Float, default=0.0)
    tds = Column(Float, default=0.0)

    # Calculated Fields
    overall_status = Column(String(50), nullable=False, index=True)
    # COMPLETED | IN PROCESS | PROCESSED / PENDING FINAL COMPLETION | UNPROCESSED
    grn_status = Column(String(20), nullable=False, index=True)
    # COMPLETED | PENDING
    ssc_status = Column(String(50), nullable=False, index=True)
    # NOT SUBMITTED | UPLOADED IN SSC | HARD COPY RECEIVED | SENT TO F&A | COMPLETED
    calculated_due_date = Column(String(20), nullable=True, index=True)
    days_remaining = Column(Integer, default=0)
    days_overdue = Column(Integer, default=0)
    payment_due_category = Column(String(30), nullable=False, index=True)
    # NOT DUE | DUE SOON | DUE TODAY | OVERDUE | COMPLETED

    is_non_billable = Column(Boolean, default=False, index=True)
    is_duplicate = Column(Boolean, default=False, index=True)

    dataset = relationship("DatasetMeta", back_populates="invoices")

Index("idx_invoice_search", Invoice.invoice_number, Invoice.vendor_name, Invoice.po_number, Invoice.grn_number)


# --- Pydantic Schemas for API ---

class DatasetInfo(BaseModel):
    id: int
    filename: str
    sheet_name: str
    uploaded_at: str
    total_records: int
    total_invoice_value: float
    total_amount_payable: float
    is_active: bool

class InvoiceDetail(BaseModel):
    id: int
    unit: Optional[str] = None
    bbu_number: Optional[str] = None
    item_description: Optional[str] = None
    vendor_name: Optional[str] = None
    po_number: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    grn_number: Optional[str] = None
    grn_date: Optional[str] = None
    basic_amount: float = 0.0
    gross_invoice_total: float = 0.0
    total_amount_payable: float = 0.0
    ssc_request_number: Optional[str] = None
    ssc_upload_date: Optional[str] = None
    hard_copy_received_date: Optional[str] = None
    hard_copy_sent_date: Optional[str] = None
    payment_due_days_raw: Optional[str] = None
    invoice_processing_status: Optional[str] = None
    processed: Optional[float] = None
    inprocess: Optional[float] = None
    remark_closure_date: Optional[str] = None
    kz_number: Optional[str] = None
    kz_date: Optional[str] = None
    rt: float = 0.0
    ld: float = 0.0
    ka: float = 0.0
    kd: float = 0.0
    tds: float = 0.0
    overall_status: str
    grn_status: str
    ssc_status: str
    calculated_due_date: Optional[str] = None
    days_remaining: int = 0
    days_overdue: int = 0
    payment_due_category: str
    is_non_billable: bool = False
    is_duplicate: bool = False

class KPIData(BaseModel):
    total_records: int
    total_invoice_value: float
    total_basic_amount: float
    total_amount_payable: float
    completed_count: int
    completed_value: float
    completed_percentage: float
    in_process_count: int
    in_process_value: float
    in_process_percentage: float
    processed_count: int
    processed_value: float
    processed_percentage: float
    unprocessed_count: int
    unprocessed_value: float
    unprocessed_percentage: float
    incomplete_count: int
    incomplete_value: float
    incomplete_percentage: float
    billable_count: int
    billable_completed_count: int
    billable_completion_pct: float
    non_billable_count: int
    non_billable_completed_count: int
    non_billable_completion_pct: float
    summary_sentence: str

class DonutItem(BaseModel):
    name: str
    count: int
    value: float
    color: str

class MonthlyTrendItem(BaseModel):
    month: str
    year_month: str
    count: int
    value: float
    completed_count: int
    in_process_count: int
    processed_count: int
    unprocessed_count: int
    completion_pct: float

class VendorMetricItem(BaseModel):
    vendor_name: str
    total_records: int
    total_value: float
    completed_count: int
    in_process_count: int
    processed_count: int
    unprocessed_count: int
    pending_count: int
    pending_value: float
    overdue_count: int
    overdue_value: float
    completion_pct: float

class ChartsData(BaseModel):
    status_donut: List[DonutItem]
    monthly_trend: List[MonthlyTrendItem]
    grn_progress: Dict[str, Any]
    ssc_progress: List[Dict[str, Any]]
    payment_due_aging: List[Dict[str, Any]]
    top_vendors_by_pending_value: List[VendorMetricItem]
    top_vendors_by_pending_records: List[VendorMetricItem]
    vendor_status_breakdown: List[VendorMetricItem]

class ActionItem(BaseModel):
    id: int
    invoice_number: Optional[str]
    vendor_name: Optional[str]
    po_number: Optional[str]
    invoice_date: Optional[str]
    gross_invoice_total: float
    overall_status: str
    grn_status: str
    ssc_status: str
    payment_due_category: str
    calculated_due_date: Optional[str]
    days_overdue: int
    priority: str  # CRITICAL, HIGH, MEDIUM, LOW
    issue_type: str
    issue_description: str

class DataQualitySummary(BaseModel):
    total_records: int
    missing_invoice_number: int
    missing_vendor: int
    missing_po: int
    missing_grn: int
    missing_grn_date: int
    missing_ssc_request: int
    missing_invoice_date: int
    missing_amount: int
    invalid_dates: int
    invalid_amounts: int
    duplicate_records: int
    affected_record_ids: Dict[str, List[int]]

class ExcelPreviewResponse(BaseModel):
    filename: str
    sheet_names: List[str]
    detected_sheet: str
    total_rows: int
    total_columns: int
    required_found: List[str]
    required_missing: List[str]
    optional_found: List[str]
    sample_rows: List[Dict[str, Any]]
    validation_status: str  # VALID | ERROR
    validation_message: str
    duplicate_count: int
    blank_invoice_count: int
