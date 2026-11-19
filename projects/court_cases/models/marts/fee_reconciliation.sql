-- Filings whose court fee is not fully paid, or paid more than once over.
select
    fees.filing_id,
    fees.case_id,
    cases.court_id,
    fees.document_type,
    fees.filed_on,
    fees.fee_due_inr,
    fees.fee_paid_inr,
    fees.fee_outstanding_inr,
    case
        when fees.fee_paid_inr = 0 then 'unpaid'
        when fees.fee_outstanding_inr > 0 then 'part_paid'
        else 'overpaid'
    end as reconciliation_status
from {{ ref('int_filing_fees') }} as fees
inner join {{ ref('stg_cases') }} as cases on fees.case_id = cases.case_id
where fees.fee_outstanding_inr <> 0
