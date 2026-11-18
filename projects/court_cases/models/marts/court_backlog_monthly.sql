-- Cases filed and disposed per court and month, and the running backlog.
with months as (
    select distinct court_id, date_trunc('month', filed_on) as month from {{ ref('fct_cases') }}
    union
    select distinct court_id, date_trunc('month', final_order_date) from {{ ref('fct_cases') }}
    where final_order_date is not null
),

filed as (
    select court_id, date_trunc('month', filed_on) as month, count(*) as cases_filed
    from {{ ref('fct_cases') }}
    group by 1, 2
),

disposed as (
    select court_id, date_trunc('month', final_order_date) as month, count(*) as cases_disposed
    from {{ ref('fct_cases') }}
    where final_order_date is not null
    group by 1, 2
)

select
    months.court_id,
    months.month,
    coalesce(filed.cases_filed, 0) as cases_filed,
    coalesce(disposed.cases_disposed, 0) as cases_disposed,
    sum(coalesce(filed.cases_filed, 0) - coalesce(disposed.cases_disposed, 0))
        over (partition by months.court_id order by months.month) as backlog
from months
left join filed on months.court_id = filed.court_id and months.month = filed.month
left join disposed on months.court_id = disposed.court_id and months.month = disposed.month
