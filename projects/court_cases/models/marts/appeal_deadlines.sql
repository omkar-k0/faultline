-- An appeal against a final order must be filed within the limitation period.
-- Fictional rule set for this synthetic project: 90 days for civil and
-- commercial, 60 for criminal, 30 for family and writ matters.
select
    cases.case_id,
    cases.court_id,
    cases.case_type,
    cases.final_outcome,
    cases.final_order_date,
    case cases.case_type
        when 'civil' then 90
        when 'commercial' then 90
        when 'criminal' then 60
        else 30
    end as limitation_days,
    cases.final_order_date + to_days(
        case cases.case_type
            when 'civil' then 90
            when 'commercial' then 90
            when 'criminal' then 60
            else 30
        end
    ) as appeal_deadline
from {{ ref('fct_cases') }} as cases
where cases.final_order_date is not null
  and cases.final_outcome in ('dismissed', 'partly_allowed')
