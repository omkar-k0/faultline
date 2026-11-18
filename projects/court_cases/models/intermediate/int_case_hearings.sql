select
    case_id,
    count(*) as hearing_count,
    count(*) filter (where is_adjourned) as adjournment_count,
    min(hearing_date) as first_hearing_date,
    max(hearing_date) as last_hearing_date,
    sum(duration_minutes) as total_hearing_minutes
from {{ ref('stg_hearings') }}
group by case_id
