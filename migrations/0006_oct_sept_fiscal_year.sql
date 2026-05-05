-- 0006_oct_sept_fiscal_year.sql
-- Add 'Oct-Sept' to the fy_calendar CHECK constraint and correct the AL + DC
-- rows in `districts` whose legacy NCES-derived value didn't match the actual
-- statutory fiscal year.
--
--   AL — Ala. Code § 16-13-140 changed the school FY to Oct 1 – Sept 30 in
--        the 2010 reform (Act 2010-528). The legacy master_districts.csv has
--        'Sept-Aug' for AL.
--   DC — D.C. Home Rule Act § 446 puts DC on the federal Oct 1 – Sept 30 FY.
--        The legacy CSV has 'July-June' for DC.

alter table districts
  drop constraint if exists districts_fy_calendar_check;

alter table districts
  add constraint districts_fy_calendar_check
  check (fy_calendar in ('July-June', 'Sept-Aug', 'Oct-Sept'));

update districts
  set fy_calendar = 'Oct-Sept', updated_at = now()
  where state_postal = 'AL' and fy_calendar = 'Sept-Aug';

update districts
  set fy_calendar = 'Oct-Sept', updated_at = now()
  where state_postal = 'DC' and fy_calendar = 'July-June';
