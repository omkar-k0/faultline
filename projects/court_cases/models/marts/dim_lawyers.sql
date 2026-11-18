with case_counts as (
    select
        lead_lawyer_id,
        count(*) as cases_led,
        count(*) filter (where case_status = 'disposed') as cases_disposed,
        count(*) filter (where final_outcome in ('allowed', 'partly_allowed')) as cases_won,
        avg(adjournment_rate) as avg_adjournment_rate
    from {{ ref('fct_cases') }}
    group by lead_lawyer_id
)

select
    lawyers.lawyer_id,
    lawyers.lawyer_name,
    lawyers.firm,
    date_diff('year', lawyers.enrolled_on, date '2026-06-30') as years_at_bar,
    coalesce(case_counts.cases_led, 0) as cases_led,
    coalesce(case_counts.cases_disposed, 0) as cases_disposed,
    coalesce(case_counts.cases_won, 0) as cases_won,
    case
        when coalesce(case_counts.cases_disposed, 0) = 0 then null
        else case_counts.cases_won * 1.0 / case_counts.cases_disposed
    end as win_rate,
    case_counts.avg_adjournment_rate
from {{ ref('stg_lawyers') }} as lawyers
left join case_counts on lawyers.lawyer_id = case_counts.lead_lawyer_id
