# LPG Refinery Data — Semantic Context, Hierarchy & Business Questions
**Version 2 — Enriched with Domain Separation, Production Models & Rejection Taxonomy**

---

## 1. Two Core Business Domains

> ⚠️ **Critical Design Principle:** Plants and Distributors are two entirely separate entities and must NOT be conflated in any query or report.

| Domain | Entity | Purpose | Key Tables |
|--------|--------|---------|------------|
| **Production** | **Plant** | Fills LPG cylinders and tracks operational performance — productivity, production volume, and quality rejections | `event_log`, `production_log`, `lpg_plant_operations`, `lpg_plant_operations_masters` |
| **Sales & Distribution** | **Distributor** | Receives filled cylinders from plants and delivers them to end consumers. Tracks bookings, pending orders, and subsidy payments | `lpg_todays_cdcms_sales_summary`, `lpg_cdcms_last_three_months_summary`, `lpg_monthly_cdcms_sales_summary`, `lpg_cdcms_subsidy_failure_statistics`, `lpg_distributor_mapping` |

The **bridge** between these two domains is `lpg_distributor_mapping.deliv_plant` → `lpg_plant_operations_masters.sap_id`, which maps which plant supplies which distributor(s).

The system also integrates with **SAP** (plant master IDs via `sap_id`) and **JDE (JD Edwards)** (distributor codes via `JDEDistributorCode`) as upstream ERP systems.

---

## 2. Data Hierarchies

### 2.1 Geographic Hierarchy (applies to both domains)
```
Zone  (ZOCode / ZOName)
  └── Region  (ROCode / ROName)
        └── Sales Area  (SACode / SAName)
              └── State  (StateCode)
                    └── District  (DistrictCode)
                          └── Taluka  (TalukaCode)
                                └── City  (CityCode)
                                      └── Distributor  (JDEDistributorCode / DistributorName)   ← Sales Domain
                                      └── Plant  (sap_id / PlantName)                           ← Production Domain
```

### 2.2 Production Domain Hierarchy
```
Plant  (sap_id / plant_id / PlantName)
  └── Carousel / System  (system_id — capacity: 24H, 48H, 72H cylinders/cycle)
        └── Filling Head  (device_id / filling_head)
              └── Cylinder Processing Event  (cyl_id_no, cyl_type: 14.2kg / 19kg)
                    ├── ✅ Production Log  (successfully filled & passed)
                    └── ❌ Event Log  (rejections → sortout or discard)
                               ├── Valve Leak Rejection
                               ├── Check Scale Rejection
                               └── O-Ring Leak Rejection
```

### 2.3 Sales / Distribution Domain Hierarchy
```
Distributor  (JDEDistributorCode / DistributorName)
  └── Consumer Segment  (ConsumerType: PMUY / NPMUY)
        └── Cylinder Type  (CylType: 14.2kg / 19kg)
              └── Order Source  (OrderSourceCode / OrderSourceName)
                    └── Order Status
                          ├── Booked  (BookingReceivedToday / BookingReceivedYesterday)
                          ├── Pending  (Pending_0D … Pending_Beyond15D)
                          └── Delivered  (TotalSalesToday / TotalSalesYesterday)
                                └── Subsidy Transfer  (PMUY: DBT/DBTL payment)
                                      └── Subsidy Failure  (PaymentErrorCode / PaymentErrorName)
```

### 2.4 Time Hierarchy
```
Financial Year  (Financial_Year — Indian FY: April to March)
  └── Year  (Execution_Year / Year)
        └── Quarter  (Quarter — Q1: Apr–Jun, Q2: Jul–Sep, Q3: Oct–Dec, Q4: Jan–Mar)
              └── Month  (Month / Month_Number)
                    └── Date  (Delivery_Date / process_date / Execution_Date / pdate)
```

### 2.5 Production Measurement Hierarchy
```
Production (Total Output)
  ├── Model 1: Production in MT (Metric Tonnes)
  │     = sum of (cylinder count × cylinder weight in kg) / 1000
  │     Columns: production_14_2kg × 14.2 + production_19kg × 19 → converted to MT
  │
  └── Model 2: Production in No. of Cylinders (in Lakhs)
        = total cylinder count / 100,000
        Columns: production_14_2kg + production_19kg → converted to lakhs
```

### 2.6 Rejection Type Hierarchy (Production Domain only)
```
Rejections (Total Faulty Cylinders Detected)
  ├── 1. Valve Leak Rejection   — gas leaking through the cylinder valve
  │         Columns: cs_handled, cs_sortout, cs_rejection %
  │
  ├── 2. Check Scale Rejection  — cylinder weight is outside acceptable tolerance
  │         Columns: gd_handled, gd_sortout, gd_rejection %
  │
  └── 3. O-Ring Leak Rejection  — gas leaking through the O-ring seal
              Columns: pt_handled, pt_sortout, pt_rejection %

For each rejection type:
  _handled  = total cylinders flagged with this fault
  _sortout  = cylinders repaired and re-admitted to production
  _rejection % = (handled - sortout) / handled × 100  [net rejection rate]
```

> **Note:** The `event_log.process_id` field maps to the rejection type by numeric code. `is_sortout = 1` means the rejected cylinder was repaired and counted in final production.

### 2.7 Productivity Metric
```
Productivity (Cylinders per Hour)
  = total_production (cylinder count) / total_net_hours
  Reported as: Productivity (Cyl/Hour)
  Available per shift type:
    - normal_productivity  (regular shift hours)
    - break_productivity   (during scheduled breaks)
    - overtime_productivity (overtime hours)
    - total_productivity   (all hours combined)
  Aggregation level: per Plant × Carousel × Date
```

---

## 3. Table-by-Table Semantic Context

### 3.1 `event_log`
**Domain:** Production
**Purpose:** Raw event stream — records every cylinder-level quality inspection event on the filling carousel. Captures both accepted and rejected cylinders as they are processed.

**Key Concepts:**
- `system_id` = Carousel ID. A carousel is a rotating filling mechanism with capacity 24H, 48H, or 72H (cylinders per cycle).
- `device_id` = Individual filling head on the carousel.
- `process_id` = Rejection type code. Maps to: Valve Leak, Check Scale, or O-Ring Leak rejection.
- `is_sortout` = 1 means the cylinder was initially rejected but repaired and re-admitted to production.
- `process_status` / `process_status32` = Bitmask status fields indicating outcome of each inspection stage.
- `cyl_type` = Cylinder weight class (14.2 kg domestic / 19 kg commercial).
- `cyl_id_no` = Unique cylinder serial/barcode ID.

**Grain:** One row per cylinder per inspection event.

**Business Questions:**
- How many cylinders were rejected vs. passed at a given plant on a given day?
- What is the Valve Leak vs. Check Scale vs. O-Ring rejection breakdown?
- Which filling heads generate the most rejections?
- What is the sortout recovery rate by rejection type?

---

### 3.2 `production_log`
**Domain:** Production
**Purpose:** Confirmed production record — one row per cylinder that completes the full filling and quality pipeline successfully (or after successful sortout). This is the source of truth for production counts.

**Key Concepts:**
- `pp01` through `pp05` machine IDs and statuses = Five sequential post-processing quality check stations (e.g., weight check → leak check → valve check → O-ring check → final pass). Each station can flag a rejection.
- `cyl_tare` = Tare (empty) weight of the cylinder in grams.
- `residual` = Residual LPG remaining in the cylinder before filling.
- `fill_time` = Duration to fill the cylinder (milliseconds or seconds).
- `check_net` = Net weight of LPG after filling — used for Check Scale validation.
- `sequence_id` = Cylinder's position on the carousel in that cycle.

**Grain:** One row per cylinder successfully processed.

**Relationship to `event_log`:** `event_log` is the event stream (all attempts including failures); `production_log` is the confirmed output (accepted cylinders only).

**Business Questions:**
- What is daily/monthly production volume per plant (in cylinders and MT)?
- What is the average fill time per carousel or plant?
- How many 14.2 kg vs. 19 kg cylinders were produced?

---

### 3.3 `lpg_plant_operations`
**Domain:** Production
**Purpose:** Aggregated daily plant performance KPI table — pre-computed by carousel × date × shift type. Primary table for production dashboards at Zone/Region/Plant level.

**Key Concepts:**

**Shift breakdown:**
- `normal_*` = Regular working hours metrics
- `break_*` = Break-period hours metrics (some filling may continue during breaks)
- `overtime_*` = Overtime hours metrics

**Per-shift metrics:**
- `*_net_hours` = Actual hours worked in that shift category
- `*_total_production` = Cylinder count produced
- `*_productivity` = Cylinders per hour (efficiency KPI)

**Rejection columns (3 types):**

| Rejection Type | Handled Column | Sortout Column | Rejection % Column |
|---|---|---|---|
| **Valve Leak Rejection** | `cs_handled` | `cs_sortout` | `cs_rejection` |
| **Check Scale Rejection** | `gd_handled` | `gd_sortout` | `gd_rejection` |
| **O-Ring Leak Rejection** | `pt_handled` | `pt_sortout` | `pt_rejection` |

**Production by cylinder type:**
- `production_14_2kg` = Count of 14.2 kg domestic cylinders filled
- `production_19kg` = Count of 19 kg commercial cylinders filled

**Production measurement conversions:**
- **Production (MT)** = `(production_14_2kg × 14.2 + production_19kg × 19) / 1000`
- **Production (No. of Cyl in Lakhs)** = `(production_14_2kg + production_19kg) / 100000`
- **Productivity (Cyl/Hour)** = `total_production / total_net_hours`

**Grain:** One row per plant (`sap_id`) × carousel × date.

**Business Questions:**
- What is today's production across all plants in MT and in lakh cylinders?
- Which plants have the highest Valve Leak Rejection rates?
- What is productivity (Cyl/Hour) by zone, region, and plant for a given date?
- How much of total production comes from overtime hours?
- What is the sortout recovery rate for O-Ring rejections across plants?

---

### 3.4 `lpg_plant_operations_masters`
**Domain:** Production (Master/Reference)
**Purpose:** Plant master lookup table. Metadata for each LPG filling plant — geographic classification, carousel configuration, and connectivity details.

**Key Concepts:**
- `sap_id` = Primary plant identifier in SAP (join key to distribution domain via `deliv_plant`).
- `plant_id` / `id` = Internal numeric plant identifier (matches `plant_id` in `event_log` and `production_log`).
- `plant_name` / `PlantName` = Human-readable plant name.
- `zone`, `region`, `SiteArea` = Geographic placement of the plant.
- `carousel_type` = Type of carousel installed (24H / 48H / 72H).
- `host_ip`, `db_user`, `db_password`, `db_database` = SCADA/PLC database credentials for real-time data pull (sensitive — access-controlled).

**Grain:** One row per plant.

**Role:** The **anchor dimension** for the Production domain. Every production event and KPI joins here for plant name/geography context.

---

### 3.5 `lpg_todays_cdcms_sales_summary`
**Domain:** Sales & Distribution
**Purpose:** Real-time snapshot (today's date) of CDCMS sales at the distributor level. Tracks booking intake, delivery completions, and order backlogs as of the current day.

**Key Concepts:**
- `JDEDistributorCode` = Distributor ID (JDE system) — joins to `lpg_distributor_mapping.jde_customer`.
- `ConsumerType` = PMUY (subsidized BPL households) or NPMUY (regular consumers).
- `CylType` = Cylinder type: 14.2 kg (domestic) / 19 kg (commercial).
- `IsPrepaid` = Whether the order was prepaid by the consumer.
- `OrderSourceCode` / `OrderSourceName` = Booking channel (e.g., IVR, mobile app, dealer counter).

**Pending order aging (delivery backlog):**

| Column | Meaning |
|--------|---------|
| `Pending_0D` | Orders pending same day (booked today, not yet delivered) |
| `Pending_1D` … `Pending_15D` | Orders delayed by 1 to 15 days from booking date |
| `Pending_Beyond15D` | Orders pending for more than 15 days |
| `pending_1_3_days` | Grouped: 1–3 day delays |
| `pending_4_7_days` | Grouped: 4–7 day delays |
| `pending_8_15_days` | Grouped: 8–15 day delays |
| `Total_Pending` | Total undelivered orders across all aging buckets |

**Sales & booking metrics:**
- `BookingReceivedToday` / `BookingReceivedYesterday` = New orders received
- `TotalSalesToday` / `TotalSalesYesterday` = Cylinders delivered
- `sales_volume` / `bookings_volume` / `pendings_volume` = Equivalent volume in MT/kg

**Grain:** One row per distributor × consumer type × cylinder type × order source.

---

### 3.6 `lpg_cdcms_last_three_months_summary`
**Domain:** Sales & Distribution
**Purpose:** Rolling 90-day historical CDCMS summary. Structurally identical to the today's summary but covers the past 3 months for trend analysis and SLA monitoring.

**Additional time dimensions:** `Month`, `Month_Number`, `Execution_Year`, `Month_Year`, `Financial_Year`.

**Grain:** One row per distributor × consumer type × cylinder type × order source × execution date.

**Use:** Trend analysis, seasonal demand detection, distributor SLA compliance review.

---

### 3.7 `lpg_monthly_cdcms_sales_summary`
**Domain:** Sales & Distribution
**Purpose:** Monthly pre-aggregated CDCMS summary — the highest-level sales roll-up table for MIS and planning.

**Key Concepts:**
- Day-level aging columns are dropped; only monthly total sales and bookings remain.
- `Quarter` field enables quarterly roll-ups.
- `sales_volume` / `bookings_volume` = Monthly MT equivalents.

**Grain:** One row per distributor × consumer type × cylinder type × month × year.

**Use:** Monthly MIS reports, KPI dashboards, annual production-vs-demand planning.

---

### 3.8 `lpg_cdcms_subsidy_failure_statistics`
**Domain:** Sales & Distribution (Subsidy Compliance)
**Purpose:** Tracks failures in government subsidy (DBTL — Direct Benefit Transfer for LPG) for PMUY consumers. Each row captures a specific payment error type at a specific distributor on a specific date, along with the count of impacted consumers and refills.

**Key Concepts:**
- `PaymentErrorCode` / `PaymentErrorName` / `PaymentErrorDecription` = Error classification (e.g., invalid Aadhaar linkage, bank account mismatch, duplicate transaction).
- `Refills` = Number of cylinder refills where the subsidy transfer failed.
- `Consumers` = Count of distinct consumers impacted by this error at this distributor.
- `Distributor_Code` / `JDEDistributorCode` / `DistributorName` = Impacted distributor.
- Full geographic hierarchy: Zone → Region → Sales Area → State → District → Taluka → City.
- `Month`, `month_number`, `Year`, `Financial_Year` = Time dimension for trend tracking.

**Grain:** One row per payment error code × distributor × delivery date.

**Business Questions:**
- Which payment error types affect the most PMUY consumers?
- Which distributors/states have the highest subsidy failure volume?
- What is the trend of DBT failures over the financial year?
- How many total refills are held up due to subsidy failures this month?

---

### 3.9 `lpg_distributor_mapping`
**Domain:** Sales & Distribution (Master/Reference)
**Purpose:** Master dimension table for distributors. Provides the cross-system ID mapping and full profile of every LPG distributor.

**Key Concepts:**
- `customer` / `customer_number` = SAP customer ID.
- `jde_customer` = JDE ERP customer code — **primary join key** for all CDCMS sales tables.
- `ukid` = Internal unique key ID.
- `deliv_plant` = SAP plant ID (`sap_id`) of the filling plant that supplies this distributor — **the bridge to the Production domain**.
- `sold_to_party` = SAP sold-to party for order creation.
- `sales_area` / `sales_org` / `dist_channel` / `division` = SAP SD org structure.
- `mkt_class_lpg` / `mkt_type_lpg` = LPG market classification and type.
- `outlet_type` / `outlet_format` / `cust_type` = Distributor outlet classification.
- `explosive_licence` / `explosive_lic_exp_dt` = Regulatory explosive handling licence (mandatory for LPG distributors).
- `peso_class_a_capacity` / `peso_class_b_capacity` = PESO-licensed LPG storage capacity.
- `agreementexpirydate` / `commisioning_date` = Distributor contract lifecycle.
- PMUY eligibility attributes: `advt_caste`, `adct_gender`, `advt_ph`, `advt_social_cat` = Social welfare categorization.
- `gstin` / `permanent_account_number` = Tax compliance identifiers.
- `condition_grp_1` through `condition_grp_5` = SAP pricing condition groups.
- `customer_delivery_block` / `all_sales_area_block` = Blocking flags.

**Grain:** One row per distributor.

**Role:** The **anchor dimension** for the Sales domain. All sales, booking, and subsidy tables use `JDEDistributorCode` to join here for distributor name, geography, and plant assignment.

---

## 4. Cross-Table Relationships (Join Keys)

| From Table | Join Column | To Table | Join Column | Domain |
|---|---|---|---|---|
| `event_log` | `plant_id` | `lpg_plant_operations_masters` | `plant_id` | Production → Production Master |
| `production_log` | `plant_id` | `lpg_plant_operations_masters` | `plant_id` | Production → Production Master |
| `lpg_plant_operations` | `sap_id` | `lpg_plant_operations_masters` | `sap_id` | Production → Production Master |
| `lpg_todays_cdcms_sales_summary` | `JDEDistributorCode` | `lpg_distributor_mapping` | `jde_customer` | Sales → Sales Master |
| `lpg_cdcms_last_three_months_summary` | `JDEDistributorCode` | `lpg_distributor_mapping` | `jde_customer` | Sales → Sales Master |
| `lpg_monthly_cdcms_sales_summary` | `DistributorName` | `lpg_distributor_mapping` | `name1` | Sales → Sales Master |
| `lpg_cdcms_subsidy_failure_statistics` | `JDEDistributorCode` | `lpg_distributor_mapping` | `jde_customer` | Sales → Sales Master |
| `lpg_distributor_mapping` | `deliv_plant` | `lpg_plant_operations_masters` | `sap_id` | **Sales ↔ Production (bridge)** |

---

## 5. KPI Reference Card

| KPI | Formula | Source Table | Level |
|-----|---------|-------------|-------|
| **Productivity (Cyl/Hour)** | `total_production / total_net_hours` | `lpg_plant_operations` | Plant / Carousel / Date |
| **Production (MT)** | `(production_14_2kg × 14.2 + production_19kg × 19) / 1000` | `lpg_plant_operations` | Plant / Date |
| **Production (Lakh Cyl)** | `(production_14_2kg + production_19kg) / 100000` | `lpg_plant_operations` | Plant / Date |
| **Valve Leak Rejection %** | `(cs_handled - cs_sortout) / cs_handled × 100` | `lpg_plant_operations` | Plant / Date |
| **Check Scale Rejection %** | `(gd_handled - gd_sortout) / gd_handled × 100` | `lpg_plant_operations` | Plant / Date |
| **O-Ring Leak Rejection %** | `(pt_handled - pt_sortout) / pt_handled × 100` | `lpg_plant_operations` | Plant / Date |
| **Sortout Recovery %** | `sortout / handled × 100` (per rejection type) | `lpg_plant_operations` | Plant / Date |
| **Total Pending Orders** | `SUM(Pending_0D … Pending_Beyond15D)` | `lpg_todays_cdcms_sales_summary` | Distributor / Date |
| **Sales Fulfillment Rate** | `TotalSalesToday / BookingReceivedToday × 100` | `lpg_todays_cdcms_sales_summary` | Distributor / Date |
| **Subsidy Failure Rate** | `SUM(Refills with failure) / Total PMUY Refills × 100` | `lpg_cdcms_subsidy_failure_statistics` | Distributor / Month |

---

## 6. Suggested Business Questions

### Production — Volume
1. What is today's production (21-Feb-2026) across all plants in MT and in lakh cylinders, broken down by zone?
2. What is the month-to-date production vs. the monthly target, by region?
3. How does 14.2 kg cylinder production compare to 19 kg production across plants this financial year?

### Production — Productivity
4. Which plants have the highest Productivity (Cyl/Hour) today, and how does it compare to their monthly average?
5. How does productivity during normal hours compare to overtime hours across zones?
6. Which carousel types (24H / 48H / 72H) are most productive on a per-hour basis?

### Production — Rejections
7. What is today's Valve Leak Rejection rate (%) by zone and plant?
8. What is today's Check Scale Rejection rate (%) by zone and plant?
9. What is today's O-Ring Leak Rejection rate (%) by zone and plant?
10. Which plants have the worst combined rejection rate, and what is their sortout recovery percentage?
11. What is the rejection trend over the last 3 months — are Valve Leak rejections increasing?

### Sales — Bookings & Delivery
12. What is the current total pending backlog across all distributors, distributed across aging buckets?
13. Which distributors have orders pending for more than 15 days (Pending_Beyond15D)?
14. What is the booking volume vs. sales volume gap this month — which regions are falling behind on fulfillment?
15. How does PMUY consumer demand (bookings) compare to NPMUY demand by zone and region?

### Subsidy & Compliance
16. What are the top 5 payment error codes by consumer impact this financial year?
17. Which distributors/regions have the highest subsidy failure volume this month?
18. How many PMUY refills are currently affected by DBT failures, and what is the state-wise breakdown?

### Cross-Domain (Production vs. Sales)
19. For each plant, how does production output (in MT) compare to the sales volume (in MT) at its supplied distributors?
20. Which zones show high production but also high pending backlogs — indicating a last-mile distribution gap?

---

## 7. Glossary

| Term | Definition |
|------|-----------|
| **Plant** | LPG cylinder filling facility. The production entity. Identified by `sap_id` / `plant_id`. |
| **Distributor** | LPG dealer who receives filled cylinders from a plant and delivers to consumers. Identified by `JDEDistributorCode`. |
| **Carousel** | Rotating filling head machine at a plant. Capacities: 24H, 48H, 72H (cylinders per cycle). Also called `system_id`. |
| **Filling Head** | Individual nozzle/station on a carousel. Also called `device_id`. |
| **Productivity (Cyl/Hr)** | Operational efficiency metric: total cylinders filled ÷ total hours worked. |
| **Production (MT)** | Total LPG output in metric tonnes: (14.2kg count × 14.2 + 19kg count × 19) ÷ 1000. |
| **Production (Lakh Cyl)** | Total cylinder count ÷ 100,000. |
| **Valve Leak Rejection** | Cylinder rejected because gas leaks through the valve. Maps to `cs_*` columns. |
| **Check Scale Rejection** | Cylinder rejected because filled weight is out of tolerance. Maps to `gd_*` columns. |
| **O-Ring Leak Rejection** | Cylinder rejected because gas leaks through the O-ring seal. Maps to `pt_*` columns. |
| **Sortout** | A rejected cylinder that was repaired/adjusted and re-admitted to production. |
| **PMUY** | Pradhan Mantri Ujjwala Yojana — government subsidized LPG scheme for BPL households. |
| **NPMUY** | Non-PMUY — regular market consumers (no government subsidy). |
| **CDCMS** | Customer Demand & Cylinder Management System — the distribution order management platform. |
| **DBT / DBTL** | Direct Benefit Transfer for LPG — subsidy amount transferred to PMUY consumer's bank account. |
| **Pending_ND** | Undelivered cylinders delayed by N days from booking date. |
| **Financial Year** | Indian FY runs April to March (e.g., FY2025-26 = Apr 2025–Mar 2026). |
| **JDE** | JD Edwards ERP — source of distributor/customer master data. |
| **SAP SD** | SAP Sales & Distribution module — org hierarchy: Sales Org → Distribution Channel → Division. |
| **PESO** | Petroleum and Explosives Safety Organisation — regulatory body for LPG storage licensing. |
| **deliv_plant / sap_id** | The bridge key connecting the Sales domain (distributors) to the Production domain (plants). |