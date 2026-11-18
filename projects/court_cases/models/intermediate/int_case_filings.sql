select
    case_id,
    count(*) as filing_count,
    sum(case when document_type = 'plaint' then 0 else 1 end) as later_filing_count,
    sum(fee_due_inr) as fee_due_inr,
    sum(fee_paid_inr) as fee_paid_inr,
    sum(fee_outstanding_inr) as fee_outstanding_inr
from {{ ref('int_filing_fees') }}
group by case_id
