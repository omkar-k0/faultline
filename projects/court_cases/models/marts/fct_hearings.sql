select
    hearings.hearing_id,
    hearings.case_id,
    cases.court_id,
    cases.case_type,
    hearings.hearing_date,
    hearings.scheduled_at_utc,
    extract(hour from hearings.scheduled_at_local) as local_hour,
    dayname(hearings.hearing_date) as weekday,
    hearings.hearing_outcome,
    hearings.adjournment_reason,
    hearings.is_adjourned,
    hearings.duration_minutes
from {{ ref('stg_hearings') }} as hearings
inner join {{ ref('stg_cases') }} as cases on hearings.case_id = cases.case_id
