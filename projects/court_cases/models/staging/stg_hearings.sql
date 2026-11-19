with hearings as (
    select * from {{ ref('raw_hearings') }}
),

cases as (
    select case_id, court_id from {{ ref('raw_cases') }}
),

courts as (
    select court_id, utc_offset_minutes from {{ ref('stg_courts') }}
)

select
    hearings.hearing_id,
    hearings.case_id,
    hearings.scheduled_at_local,
    hearings.scheduled_at_local - to_minutes(courts.utc_offset_minutes) as scheduled_at_utc,
    cast(hearings.scheduled_at_local as date) as hearing_date,
    hearings.outcome as hearing_outcome,
    nullif(hearings.adjournment_reason, '') as adjournment_reason,
    hearings.duration_minutes,
    hearings.outcome = 'adjourned' as is_adjourned
from hearings
left join cases on hearings.case_id = cases.case_id
left join courts on cases.court_id = courts.court_id
