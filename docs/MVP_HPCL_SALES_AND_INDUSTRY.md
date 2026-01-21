# Helios Ops Intelligence — MVP Plan  
## HPCL Sales Performance & Industry Comparison

This document defines the **exact MVP scope and steps** to build an AI-assisted
sales performance and industry-relative analytics layer for HPCL,
using the provided Postgres tables and business rules.

The MVP focuses on:
- Actual vs Target performance
- Pace / run-rate analysis
- Regional & Sales Area (SA) drilldowns
- Product contribution analysis
- “How am I performing relative to industry?” questions
- Clear, explainable, actionable insights

---

## 1. MVP Business Questions (In Scope)

The MVP must reliably answer:

1. How am I performing **vs target** by:
   - SBU
   - Zone
   - Region
   - Sales Area (SA)
   - Product

2. How is performance **tracking vs pace**?
   - Required run-rate vs current run-rate
   - Risk of missing targets

3. Why is sales **down in a specific SA or region**  
   (e.g., *Tenali, South Zone*)?

4. How am I performing **relative to industry**?
   - Market share context
   - PSU vs Private comparison
   - HPCL growth vs industry growth

---

## 2. Source Tables (As Provided)

### 2.1 Actual Sales
**`MOM_DAY_LEVEL_DATA`**
- Grain: DAY × PRODUCT × SALES AREA
- Measures:
  - `NETWEIGHT_TMT`
  - `NETWEIGHT_KG`
- Dimensions:
  - SBU, Zone, Region, SalesArea
  - Product
  - Fiscal Year, Month, Day

---

### 2.2 Targets & Pace Metadata
**`M60_LEVEL_METADATA`**
- Grain: MONTH × PRODUCT × SALES AREA
- Measures:
  - `TARGET_QTY_TMT`
  - `Rate_Per_Day_Required_MMT`
  - `Rate_per_day_current_MMT`
  - `Pending_Days`
  - `Act_Tgt_Achievement`

---

### 2.3 Industry Performance
**`INDUSTRY_PERFORMANCE`**
- Grain: MONTH × PRODUCT × STATE × COMPANY
- Measures:
  - `netweight_tmt`
- Dimensions:
  - `company_name`
  - `psu_pvt`
  - `productname`
  - `statename`
  - `month_name`
  - `fiscal_year`

---

## 3. Mandatory Data Constraints (NON-NEGOTIABLE)

The following SBU filter **must be applied everywhere**  
(staging models, facts, AI SQL guardrails):

```sql
SBU_Name != '0'
AND SBU_Name NOT IN (
  'Common',
  'Mumbai Ref',
  'Renewable Energy',
  'Visakh Ref'
)
