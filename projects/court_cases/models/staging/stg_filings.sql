select
    filing_id,
    case_id,
    filed_by_lawyer_id,
    document_type,
    filed_at_local,
    cast(filed_at_local as date) as filed_on,
    page_count,
    court_fee_inr
from {{ ref('raw_filings') }}
