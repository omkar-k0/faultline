with cases as (
    select * from {{ ref('stg_cases') }}
),

hearings as (
    select * from {{ ref('int_case_hearings') }}
),

filings as (
    select * from {{ ref('int_case_filings') }}
),

final_orders as (
    select * from {{ ref('int_case_final_orders') }}
)

select
    cases.case_id,
    cases.case_number,
    cases.court_id,
    cases.case_type,
    cases.case_status,
    cases.filed_on,
    cases.filed_at_utc,
    cases.lead_lawyer_id,
    cases.judge_id,
    cases.claim_amount_inr,
    final_orders.final_outcome,
    final_orders.final_order_date,
    coalesce(hearings.hearing_count, 0) as hearing_count,
    coalesce(hearings.adjournment_count, 0) as adjournment_count,
    case
        when coalesce(hearings.hearing_count, 0) = 0 then null
        else hearings.adjournment_count * 1.0 / hearings.hearing_count
    end as adjournment_rate,
    hearings.first_hearing_date,
    hearings.last_hearing_date,
    date_diff('day', cases.filed_on, final_orders.final_order_date) as days_to_disposal,
    coalesce(filings.filing_count, 0) as filing_count,
    coalesce(filings.fee_due_inr, 0) as fee_due_inr,
    coalesce(filings.fee_paid_inr, 0) as fee_paid_inr,
    coalesce(filings.fee_outstanding_inr, 0) as fee_outstanding_inr
from cases
left join hearings on cases.case_id = hearings.case_id
left join filings on cases.case_id = filings.case_id
left join final_orders on cases.case_id = final_orders.case_id
