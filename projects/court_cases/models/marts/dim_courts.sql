select
    courts.court_id,
    courts.court_name,
    courts.state,
    courts.court_level,
    count(cases.case_id) as cases_filed,
    count(cases.case_id) filter (where cases.case_status = 'pending') as cases_pending,
    count(cases.case_id) filter (where cases.case_status = 'disposed') as cases_disposed,
    avg(cases.days_to_disposal) as avg_days_to_disposal,
    avg(cases.adjournment_rate) as avg_adjournment_rate
from {{ ref('stg_courts') }} as courts
left join {{ ref('fct_cases') }} as cases on courts.court_id = cases.court_id
group by 1, 2, 3, 4
