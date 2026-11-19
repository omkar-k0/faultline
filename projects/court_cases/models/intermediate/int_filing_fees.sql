-- Court fee due per filing against what was paid for it.
with payments as (
    select filing_id, sum(amount_inr) as paid_inr, max(paid_on) as last_paid_on
    from {{ ref('stg_fee_payments') }}
    group by filing_id
)

select
    filings.filing_id,
    filings.case_id,
    filings.filed_on,
    filings.document_type,
    filings.court_fee_inr as fee_due_inr,
    coalesce(payments.paid_inr, 0) as fee_paid_inr,
    filings.court_fee_inr - coalesce(payments.paid_inr, 0) as fee_outstanding_inr,
    payments.last_paid_on
from {{ ref('stg_filings') }} as filings
left join payments on filings.filing_id = payments.filing_id
