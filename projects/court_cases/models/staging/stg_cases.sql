-- Court registers record local time. Convert to UTC with the court's offset.
with cases as (
    select * from {{ ref('raw_cases') }}
),

courts as (
    select court_id, utc_offset_minutes from {{ ref('stg_courts') }}
)

select
    cases.case_id,
    cases.case_number,
    cases.court_id,
    cases.case_type,
    cases.filed_at_local,
    cases.filed_at_local - to_minutes(courts.utc_offset_minutes) as filed_at_utc,
    cast(cases.filed_at_local as date) as filed_on,
    cases.petitioner_party_id,
    cases.respondent_party_id,
    cases.lead_lawyer_id,
    cases.judge_id,
    cases.status as case_status,
    cases.claim_amount_inr,
    cases.disposed_on
from cases
left join courts on cases.court_id = courts.court_id
