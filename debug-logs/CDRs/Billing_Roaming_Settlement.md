# Billing_Roaming_Settlement_Reconciliation

_Generated: 2026-04-24T10:37:01.238052Z_
_Data directory: `/Users/algofusion/pythonProject1/pycharm_codes/CDR_DATA_SAMPLES`_
_Match window: **900s** (Billing rating_timestamp vs Roaming_Settlement event_time, subscriber last-8 digits)_

## Why this reconciliation is critical

Interconnect and roaming settlement directly affects cash position, partner disputes, and regulatory reporting. Mismatched durations, missing TAP records, wrong partner or service mapping, unbooked FX, or amount deltas drive revenue leakage, duplicate payments, and audit findings.

## Executive summary

| Detection area | Count |
|----------------|-------|
| Matched Billing ↔ Roaming_Settlement pairs (best candidate in window) | 696 |
| Duration mismatches (Mediation vs Roaming_Settlement) | 0 |
| Missing roaming — Roaming_Settlement rows unmatched to Billing | 504 |
| Missing roaming — Billing rows with no Roaming_Settlement match | 504 |
| Incorrect partner / routing tags (heuristic) | 679 |
| Currency conversion / FX review (Roaming_Settlement vs inferred home currency) | 466 |
| Settlement disputes (amount delta on matched pair) | 15 |

---

## 1. Duration mismatches

Best Billing↔Roaming_Settlement match: Mediation usage duration vs Roaming_Settlement duration_sec beyond tolerance.

**Count:** 0

```json
[]
```

---

## 2. Missing roaming events

Roaming_Settlement inbound rows with no Billing partner in the join window (missing settlement anchor); and Billing rows with no Roaming_Settlement candidate (no roaming/interconnect file line for that subscriber/time).

**Roaming_Settlement unmatched:** 504

```json
[
  {
    "Roaming_Settlement_record_id": "697",
    "msisdn": "491686318552",
    "partner_code": "PRTDE02"
  },
  {
    "Roaming_Settlement_record_id": "698",
    "msisdn": "494052426996",
    "partner_code": "PRTUSA2"
  },
  {
    "Roaming_Settlement_record_id": "699",
    "msisdn": "491379640497",
    "partner_code": "PRTARE1"
  },
  {
    "Roaming_Settlement_record_id": "700",
    "msisdn": "497849082456",
    "partner_code": "PRTDE02"
  },
  {
    "Roaming_Settlement_record_id": "701",
    "msisdn": "493571338447",
    "partner_code": "PRTDE02"
  },
  {
    "Roaming_Settlement_record_id": "702",
    "msisdn": "496607664712",
    "partner_code": "PRTUK01"
  },
  {
    "Roaming_Settlement_record_id": "703",
    "msisdn": "495832697360",
    "partner_code": "PRTUSA2"
  },
  {
    "Roaming_Settlement_record_id": "704",
    "msisdn": "492859683451",
    "partner_code": "PRTUSA2"
  },
  {
    "Roaming_Settlement_record_id": "705",
    "msisdn": "495883499605",
    "partner_code": "PRTUK01"
  },
  {
    "Roaming_Settlement_record_id": "706",
    "msisdn": "496940948718",
    "partner_code": "PRTFRA3"
  },
  {
    "Roaming_Settlement_record_id": "707",
    "msisdn": "491870013651",
    "partner_code": "PRTARE1"
  },
  {
    "Roaming_Settlement_record_id": "708",
    "msisdn": "496842122898",
    "partner_code": "PRTARE1"
  },
  {
    "Roaming_Settlement_record_id": "709",
    "msisdn": "491531043080",
    "partner_code": "PRTDE02"
  },
  {
    "Roaming_Settlement_record_id": "710",
    "msisdn": "493595184691",
    "partner_code": "PRTFRA3"
  },
  {
    "Roaming_Settlement_record_id": "711",
    "msisdn": "493333065597",
    "partner_code": "PRTARE1"
  },
  {
    "Roaming_Settlement_record_id": "712",
    "msisdn": "492808551729",
    "partner_code": "PRTDE02"
  },
  {
    "Roaming_Settlement_record_id": "713",
    "msisdn": "495640605643",
    "partner_code": "PRTUK01"
  },
  {
    "Roaming_Settlement_record_id": "714",
    "msisdn": "496229822505",
    "partner_code": "PRTUSA2"
  },
  {
    "Roaming_Settlement_record_id": "715",
    "msisdn": "494462042457",
    "partner_code": "PRTDE02"
  },
  {
    "Roaming_Settlement_record_id": "716",
    "msisdn": "497438572903",
    "partner_code": "PRTDE02"
  },
  {
    "Roaming_Settlement_record_id": "717",
    "msisdn": "497876597324",
    "partner_code": "PRTFRA3"
  },
  {
    "Roaming_Settlement_record_id": "718",
    "msisdn": "495170245526",
    "partner_code": "PRTDE02"
  },
  {
    "Roaming_Settlement_record_id": "719",
    "msisdn": "497322044840",
    "partner_code": "PRTFRA3"
  },
  {
    "Roaming_Settlement_record_id": "720",
    "msisdn": "494334772048",
    "partner_code": "PRTFRA3"
  },
  {
    "Roaming_Settlement_record_id": "721",
    "msisdn": "499655987694",
    "partner_code": "PRTUSA2"
  },
  {
    "Roaming_Settlement_record_id": "722",
    "msisdn": "498244649566",
    "partner_code": "PRTARE1"
  },
  {
    "Roaming_Settlement_record_id": "723",
    "msisdn": "497348579494",
    "partner_code": "PRTUK01"
  },
  {
    "Roaming_Settlement_record_id": "724",
    "msisdn": "491587449150",
    "partner_code": "PRTFRA3"
  },
  {
    "Roaming_Settlement_record_id": "725",
    "msisdn": "498914908769",
    "partner_code": "PRTUSA2"
  },
  {
    "Roaming_Settlement_record_id": "726",
    "msisdn": "492249093427",
    "partner_code": "PRTUK01"
  },
  {
    "Roaming_Settlement_record_id": "727",
    "msisdn": "499372995204",
    "partner_code": "PRTFRA3"
  },
  {
    "Roaming_Settlement_record_id": "728",
    "msisdn": "495857605057",
    "partner_code": "PRTARE1"
  },
  {
    "Roaming_Settlement_record_id": "729",
    "msisdn": "498465291893",
    "partner_code": "PRTDE02"
  },
  {
    "Roaming_Settlement_record_id": "730",
    "msisdn": "492117384962",
    "partner_code": "PRTARE1"
  },
  {
    "Roaming_Settlement_record_id": "731",
    "msisdn": "494405710620",
    "partner_code": "PRTFRA3"
  },
  {
    "Roaming_Settlement_record_id": "732",
    "msisdn": "490225092011",
    "partner_code": "PRTUK01"
  },
  {
    "Roaming_Settlement_record_id": "733",
    "msisdn": "497976040271",
    "partner_code": "PRTARE1"
  },
  {
    "Roaming_Settlement_record_id": "734",
    "msisdn": "498893457649",
    "partner_code": "PRTUK01"
  },
  {
    "Roaming_Settlement_record_id": "735",
    "msisdn": "496318829787",
    "partner_code": "PRTUSA2"
  },
  {
    "Roaming_Settlement_record_id": "736",
    "msisdn": "498452405416",
    "partner_code": "PRTFRA3"
  }
]
```

**Billing without Roaming_Settlement match:** 504

```json
[
  {
    "Billing_id": "3",
    "cdr_id": "3",
    "subscriber_id": "SUB-01226916"
  },
  {
    "Billing_id": "5",
    "cdr_id": "5",
    "subscriber_id": "SUB-37631165"
  },
  {
    "Billing_id": "7",
    "cdr_id": "7",
    "subscriber_id": "SUB-79911838"
  },
  {
    "Billing_id": "12",
    "cdr_id": "13",
    "subscriber_id": "SUB-08053100"
  },
  {
    "Billing_id": "16",
    "cdr_id": "18",
    "subscriber_id": "SUB-40139904"
  },
  {
    "Billing_id": "17",
    "cdr_id": "19",
    "subscriber_id": "SUB-70348247"
  },
  {
    "Billing_id": "21",
    "cdr_id": "23",
    "subscriber_id": "SUB-45171236"
  },
  {
    "Billing_id": "25",
    "cdr_id": "28",
    "subscriber_id": "SUB-47679764"
  },
  {
    "Billing_id": "27",
    "cdr_id": "30",
    "subscriber_id": "SUB-79955271"
  },
  {
    "Billing_id": "28",
    "cdr_id": "31",
    "subscriber_id": "SUB-88925546"
  },
  {
    "Billing_id": "31",
    "cdr_id": "34",
    "subscriber_id": "SUB-36971179"
  },
  {
    "Billing_id": "32",
    "cdr_id": "36",
    "subscriber_id": "SUB-79627570"
  },
  {
    "Billing_id": "37",
    "cdr_id": "43",
    "subscriber_id": "SUB-44375758"
  },
  {
    "Billing_id": "40",
    "cdr_id": "46",
    "subscriber_id": "SUB-87851910"
  },
  {
    "Billing_id": "41",
    "cdr_id": "47",
    "subscriber_id": "SUB-46226567"
  },
  {
    "Billing_id": "42",
    "cdr_id": "48",
    "subscriber_id": "SUB-06738302"
  },
  {
    "Billing_id": "46",
    "cdr_id": "53",
    "subscriber_id": "SUB-58662961"
  },
  {
    "Billing_id": "49",
    "cdr_id": "56",
    "subscriber_id": "SUB-96561014"
  },
  {
    "Billing_id": "50",
    "cdr_id": "57",
    "subscriber_id": "SUB-82825867"
  },
  {
    "Billing_id": "53",
    "cdr_id": "64",
    "subscriber_id": "SUB-69146303"
  },
  {
    "Billing_id": "61",
    "cdr_id": "75",
    "subscriber_id": "SUB-70246299"
  },
  {
    "Billing_id": "62",
    "cdr_id": "77",
    "subscriber_id": "SUB-34944665"
  },
  {
    "Billing_id": "69",
    "cdr_id": "88",
    "subscriber_id": "SUB-18268861"
  },
  {
    "Billing_id": "70",
    "cdr_id": "89",
    "subscriber_id": "SUB-80133613"
  },
  {
    "Billing_id": "75",
    "cdr_id": "95",
    "subscriber_id": "SUB-21038862"
  },
  {
    "Billing_id": "76",
    "cdr_id": "96",
    "subscriber_id": "SUB-81806356"
  },
  {
    "Billing_id": "78",
    "cdr_id": "98",
    "subscriber_id": "SUB-89554393"
  },
  {
    "Billing_id": "81",
    "cdr_id": "101",
    "subscriber_id": "SUB-66322702"
  },
  {
    "Billing_id": "83",
    "cdr_id": "104",
    "subscriber_id": "SUB-07740649"
  },
  {
    "Billing_id": "84",
    "cdr_id": "105",
    "subscriber_id": "SUB-21442703"
  },
  {
    "Billing_id": "87",
    "cdr_id": "108",
    "subscriber_id": "SUB-11810220"
  },
  {
    "Billing_id": "88",
    "cdr_id": "109",
    "subscriber_id": "SUB-83928861"
  },
  {
    "Billing_id": "89",
    "cdr_id": "110",
    "subscriber_id": "SUB-33504888"
  },
  {
    "Billing_id": "90",
    "cdr_id": "111",
    "subscriber_id": "SUB-60480589"
  },
  {
    "Billing_id": "95",
    "cdr_id": "117",
    "subscriber_id": "SUB-97767199"
  },
  {
    "Billing_id": "98",
    "cdr_id": "120",
    "subscriber_id": "SUB-62914504"
  },
  {
    "Billing_id": "101",
    "cdr_id": "124",
    "subscriber_id": "SUB-02278469"
  },
  {
    "Billing_id": "103",
    "cdr_id": "127",
    "subscriber_id": "SUB-76580185"
  },
  {
    "Billing_id": "108",
    "cdr_id": "134",
    "subscriber_id": "SUB-25349292"
  },
  {
    "Billing_id": "111",
    "cdr_id": "139",
    "subscriber_id": "SUB-51509398"
  }
]
```

---

## 3. Incorrect partner routing tags

Roaming_Settlement call_type inconsistent with Mediation service_type for the same cdr_id; or IMSI/partner vs subscriber geography heuristic anomalies.

**Count:** 679

```json
[
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "4",
    "cdr_id": 4,
    "Roaming_Settlement_record_id": 489,
    "Mediation_service_type": "SMS",
    "Roaming_Settlement_call_type": "MOC",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_IMSI_VS_PARTNER_ANOMALY",
    "Billing_id": "4",
    "cdr_id": 4,
    "Roaming_Settlement_record_id": 489,
    "Roaming_Settlement_imsi_prefix": "404606",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "detail": "Indian IMSI prefix with non-Indian partner code on +91 subscriber (verify clearing house)"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "6",
    "cdr_id": 6,
    "Roaming_Settlement_record_id": 683,
    "Mediation_service_type": "Voice",
    "Roaming_Settlement_call_type": "GPRS",
    "Roaming_Settlement_partner_code": "PRTARE1",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "8",
    "cdr_id": 8,
    "Roaming_Settlement_record_id": 612,
    "Mediation_service_type": "Voice",
    "Roaming_Settlement_call_type": "SMSMO",
    "Roaming_Settlement_partner_code": "PRTUK01",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_IMSI_VS_PARTNER_ANOMALY",
    "Billing_id": "10",
    "cdr_id": 11,
    "Roaming_Settlement_record_id": 619,
    "Roaming_Settlement_imsi_prefix": "404200",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "detail": "Indian IMSI prefix with non-Indian partner code on +91 subscriber (verify clearing house)"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "13",
    "cdr_id": 14,
    "Roaming_Settlement_record_id": 415,
    "Mediation_service_type": "Data",
    "Roaming_Settlement_call_type": "MOC",
    "Roaming_Settlement_partner_code": "PRTARE1",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "14",
    "cdr_id": 15,
    "Roaming_Settlement_record_id": 175,
    "Mediation_service_type": "Voice",
    "Roaming_Settlement_call_type": "GPRS",
    "Roaming_Settlement_partner_code": "PRTFRA3",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "15",
    "cdr_id": 17,
    "Roaming_Settlement_record_id": 106,
    "Mediation_service_type": "Data",
    "Roaming_Settlement_call_type": "MOC",
    "Roaming_Settlement_partner_code": "PRTUK01",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "18",
    "cdr_id": 20,
    "Roaming_Settlement_record_id": 302,
    "Mediation_service_type": "Data",
    "Roaming_Settlement_call_type": "SMSMO",
    "Roaming_Settlement_partner_code": "PRTDE02",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_IMSI_VS_PARTNER_ANOMALY",
    "Billing_id": "18",
    "cdr_id": 20,
    "Roaming_Settlement_record_id": 302,
    "Roaming_Settlement_imsi_prefix": "404323",
    "Roaming_Settlement_partner_code": "PRTDE02",
    "detail": "Indian IMSI prefix with non-Indian partner code on +91 subscriber (verify clearing house)"
  },
  {
    "rule": "PARTNER_ROUTING_IMSI_VS_PARTNER_ANOMALY",
    "Billing_id": "19",
    "cdr_id": 21,
    "Roaming_Settlement_record_id": 260,
    "Roaming_Settlement_imsi_prefix": "404114",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "detail": "Indian IMSI prefix with non-Indian partner code on +91 subscriber (verify clearing house)"
  },
  {
    "rule": "PARTNER_ROUTING_IMSI_VS_PARTNER_ANOMALY",
    "Billing_id": "20",
    "cdr_id": 22,
    "Roaming_Settlement_record_id": 57,
    "Roaming_Settlement_imsi_prefix": "404470",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "detail": "Indian IMSI prefix with non-Indian partner code on +91 subscriber (verify clearing house)"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "22",
    "cdr_id": 24,
    "Roaming_Settlement_record_id": 531,
    "Mediation_service_type": "Data",
    "Roaming_Settlement_call_type": "SMSMO",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_IMSI_VS_PARTNER_ANOMALY",
    "Billing_id": "22",
    "cdr_id": 24,
    "Roaming_Settlement_record_id": 531,
    "Roaming_Settlement_imsi_prefix": "404771",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "detail": "Indian IMSI prefix with non-Indian partner code on +91 subscriber (verify clearing house)"
  },
  {
    "rule": "PARTNER_ROUTING_IMSI_VS_PARTNER_ANOMALY",
    "Billing_id": "23",
    "cdr_id": 25,
    "Roaming_Settlement_record_id": 212,
    "Roaming_Settlement_imsi_prefix": "404981",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "detail": "Indian IMSI prefix with non-Indian partner code on +91 subscriber (verify clearing house)"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "24",
    "cdr_id": 26,
    "Roaming_Settlement_record_id": 287,
    "Mediation_service_type": "SMS",
    "Roaming_Settlement_call_type": "MOC",
    "Roaming_Settlement_partner_code": "PRTFRA3",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_IMSI_VS_PARTNER_ANOMALY",
    "Billing_id": "26",
    "cdr_id": 29,
    "Roaming_Settlement_record_id": 73,
    "Roaming_Settlement_imsi_prefix": "404357",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "detail": "Indian IMSI prefix with non-Indian partner code on +91 subscriber (verify clearing house)"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "29",
    "cdr_id": 32,
    "Roaming_Settlement_record_id": 539,
    "Mediation_service_type": "Voice",
    "Roaming_Settlement_call_type": "GPRS",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_IMSI_VS_PARTNER_ANOMALY",
    "Billing_id": "29",
    "cdr_id": 32,
    "Roaming_Settlement_record_id": 539,
    "Roaming_Settlement_imsi_prefix": "404688",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "detail": "Indian IMSI prefix with non-Indian partner code on +91 subscriber (verify clearing house)"
  },
  {
    "rule": "PARTNER_ROUTING_IMSI_VS_PARTNER_ANOMALY",
    "Billing_id": "30",
    "cdr_id": 33,
    "Roaming_Settlement_record_id": 501,
    "Roaming_Settlement_imsi_prefix": "404574",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "detail": "Indian IMSI prefix with non-Indian partner code on +91 subscriber (verify clearing house)"
  },
  {
    "rule": "PARTNER_ROUTING_IMSI_VS_PARTNER_ANOMALY",
    "Billing_id": "33",
    "cdr_id": 37,
    "Roaming_Settlement_record_id": 453,
    "Roaming_Settlement_imsi_prefix": "404778",
    "Roaming_Settlement_partner_code": "PRTDE02",
    "detail": "Indian IMSI prefix with non-Indian partner code on +91 subscriber (verify clearing house)"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "34",
    "cdr_id": 38,
    "Roaming_Settlement_record_id": 567,
    "Mediation_service_type": "Data",
    "Roaming_Settlement_call_type": "MOC",
    "Roaming_Settlement_partner_code": "PRTUK01",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "35",
    "cdr_id": 39,
    "Roaming_Settlement_record_id": 504,
    "Mediation_service_type": "Voice",
    "Roaming_Settlement_call_type": "SMSMO",
    "Roaming_Settlement_partner_code": "PRTUK01",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_IMSI_VS_PARTNER_ANOMALY",
    "Billing_id": "36",
    "cdr_id": 40,
    "Roaming_Settlement_record_id": 64,
    "Roaming_Settlement_imsi_prefix": "404178",
    "Roaming_Settlement_partner_code": "PRTDE02",
    "detail": "Indian IMSI prefix with non-Indian partner code on +91 subscriber (verify clearing house)"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "39",
    "cdr_id": 45,
    "Roaming_Settlement_record_id": 35,
    "Mediation_service_type": "SMS",
    "Roaming_Settlement_call_type": "VOLTE",
    "Roaming_Settlement_partner_code": "PRTUK01",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "44",
    "cdr_id": 51,
    "Roaming_Settlement_record_id": 378,
    "Mediation_service_type": "SMS",
    "Roaming_Settlement_call_type": "VOLTE",
    "Roaming_Settlement_partner_code": "PRTARE1",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "45",
    "cdr_id": 52,
    "Roaming_Settlement_record_id": 265,
    "Mediation_service_type": "SMS",
    "Roaming_Settlement_call_type": "MTC",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_IMSI_VS_PARTNER_ANOMALY",
    "Billing_id": "45",
    "cdr_id": 52,
    "Roaming_Settlement_record_id": 265,
    "Roaming_Settlement_imsi_prefix": "404632",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "detail": "Indian IMSI prefix with non-Indian partner code on +91 subscriber (verify clearing house)"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "47",
    "cdr_id": 54,
    "Roaming_Settlement_record_id": 481,
    "Mediation_service_type": "SMS",
    "Roaming_Settlement_call_type": "VOLTE",
    "Roaming_Settlement_partner_code": "PRTARE1",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "48",
    "cdr_id": 55,
    "Roaming_Settlement_record_id": 161,
    "Mediation_service_type": "Data",
    "Roaming_Settlement_call_type": "VOLTE",
    "Roaming_Settlement_partner_code": "PRTARE1",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "51",
    "cdr_id": 61,
    "Roaming_Settlement_record_id": 624,
    "Mediation_service_type": "Voice",
    "Roaming_Settlement_call_type": "SMSMO",
    "Roaming_Settlement_partner_code": "PRTFRA3",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "52",
    "cdr_id": 63,
    "Roaming_Settlement_record_id": 343,
    "Mediation_service_type": "Voice",
    "Roaming_Settlement_call_type": "GPRS",
    "Roaming_Settlement_partner_code": "PRTDE02",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_IMSI_VS_PARTNER_ANOMALY",
    "Billing_id": "52",
    "cdr_id": 63,
    "Roaming_Settlement_record_id": 343,
    "Roaming_Settlement_imsi_prefix": "404258",
    "Roaming_Settlement_partner_code": "PRTDE02",
    "detail": "Indian IMSI prefix with non-Indian partner code on +91 subscriber (verify clearing house)"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "54",
    "cdr_id": 67,
    "Roaming_Settlement_record_id": 430,
    "Mediation_service_type": "Voice",
    "Roaming_Settlement_call_type": "GPRS",
    "Roaming_Settlement_partner_code": "PRTARE1",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  },
  {
    "rule": "PARTNER_ROUTING_CALL_TYPE_MISMATCH",
    "Billing_id": "55",
    "cdr_id": 68,
    "Roaming_Settlement_record_id": 688,
    "Mediation_service_type": "SMS",
    "Roaming_Settlement_call_type": "VOLTE",
    "Roaming_Settlement_partner_code": "PRTARE1",
    "detail": "Roaming_Settlement call_type not in expected set for Mediation service_type"
  }
]
```

---

## 4. Currency conversion errors (review)

Matched pairs where Roaming_Settlement currency differs from inferred home currency from Mediation MSISDN (FX / clearing validation).

**Count:** 466

```json
[
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "1",
    "cdr_id": "1",
    "Roaming_Settlement_record_id": 674,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "GBP",
    "Billing_final_amount": "88.51",
    "Roaming_Settlement_charged_amount": "88.51",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "2",
    "cdr_id": "2",
    "Roaming_Settlement_record_id": 197,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "GBP",
    "Billing_final_amount": "64.26",
    "Roaming_Settlement_charged_amount": "64.26",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "4",
    "cdr_id": "4",
    "Roaming_Settlement_record_id": 489,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "GBP",
    "Billing_final_amount": "128.17",
    "Roaming_Settlement_charged_amount": "128.17",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "9",
    "cdr_id": "10",
    "Roaming_Settlement_record_id": 611,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "USD",
    "Billing_final_amount": "132.96",
    "Roaming_Settlement_charged_amount": "132.96",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "10",
    "cdr_id": "11",
    "Roaming_Settlement_record_id": 619,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "EUR",
    "Billing_final_amount": "32.89",
    "Roaming_Settlement_charged_amount": "32.89",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "11",
    "cdr_id": "12",
    "Roaming_Settlement_record_id": 224,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "AED",
    "Billing_final_amount": "62.35",
    "Roaming_Settlement_charged_amount": "62.35",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "13",
    "cdr_id": "14",
    "Roaming_Settlement_record_id": 415,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "USD",
    "Billing_final_amount": "47.60",
    "Roaming_Settlement_charged_amount": "47.60",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "14",
    "cdr_id": "15",
    "Roaming_Settlement_record_id": 175,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "GBP",
    "Billing_final_amount": "25.62",
    "Roaming_Settlement_charged_amount": "25.62",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "15",
    "cdr_id": "17",
    "Roaming_Settlement_record_id": 106,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "GBP",
    "Billing_final_amount": "77.86",
    "Roaming_Settlement_charged_amount": "77.86",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "20",
    "cdr_id": "22",
    "Roaming_Settlement_record_id": 57,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "AED",
    "Billing_final_amount": "32.63",
    "Roaming_Settlement_charged_amount": "32.63",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "23",
    "cdr_id": "25",
    "Roaming_Settlement_record_id": 212,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "GBP",
    "Billing_final_amount": "29.10",
    "Roaming_Settlement_charged_amount": "29.10",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "24",
    "cdr_id": "26",
    "Roaming_Settlement_record_id": 287,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "GBP",
    "Billing_final_amount": "119.20",
    "Roaming_Settlement_charged_amount": "119.20",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "26",
    "cdr_id": "29",
    "Roaming_Settlement_record_id": 73,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "AED",
    "Billing_final_amount": "84.20",
    "Roaming_Settlement_charged_amount": "84.20",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "29",
    "cdr_id": "32",
    "Roaming_Settlement_record_id": 539,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "GBP",
    "Billing_final_amount": "103.75",
    "Roaming_Settlement_charged_amount": "103.75",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "30",
    "cdr_id": "33",
    "Roaming_Settlement_record_id": 501,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "EUR",
    "Billing_final_amount": "17.44",
    "Roaming_Settlement_charged_amount": "17.44",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "33",
    "cdr_id": "37",
    "Roaming_Settlement_record_id": 453,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "AED",
    "Billing_final_amount": "138.33",
    "Roaming_Settlement_charged_amount": "138.33",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "35",
    "cdr_id": "39",
    "Roaming_Settlement_record_id": 504,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "AED",
    "Billing_final_amount": "15.46",
    "Roaming_Settlement_charged_amount": "15.46",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "36",
    "cdr_id": "40",
    "Roaming_Settlement_record_id": 64,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "EUR",
    "Billing_final_amount": "11.74",
    "Roaming_Settlement_charged_amount": "11.74",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "38",
    "cdr_id": "44",
    "Roaming_Settlement_record_id": 432,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "GBP",
    "Billing_final_amount": "36.78",
    "Roaming_Settlement_charged_amount": "36.78",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "44",
    "cdr_id": "51",
    "Roaming_Settlement_record_id": 378,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "AED",
    "Billing_final_amount": "81.49",
    "Roaming_Settlement_charged_amount": "81.49",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "48",
    "cdr_id": "55",
    "Roaming_Settlement_record_id": 161,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "AED",
    "Billing_final_amount": "102.64",
    "Roaming_Settlement_charged_amount": "102.64",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "51",
    "cdr_id": "61",
    "Roaming_Settlement_record_id": 624,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "USD",
    "Billing_final_amount": "67.92",
    "Roaming_Settlement_charged_amount": "67.92",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "52",
    "cdr_id": "63",
    "Roaming_Settlement_record_id": 343,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "GBP",
    "Billing_final_amount": "45.08",
    "Roaming_Settlement_charged_amount": "45.08",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "54",
    "cdr_id": "67",
    "Roaming_Settlement_record_id": 430,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "AED",
    "Billing_final_amount": "49.34",
    "Roaming_Settlement_charged_amount": "49.34",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  },
  {
    "rule": "CURRENCY_VS_SUBSCRIBER_HOME_MISMATCH",
    "Billing_id": "55",
    "cdr_id": "68",
    "Roaming_Settlement_record_id": 688,
    "inferred_home_currency": "INR",
    "Roaming_Settlement_currency": "USD",
    "Billing_final_amount": "73.58",
    "Roaming_Settlement_charged_amount": "73.58",
    "detail": "Roaming_Settlement settlement currency differs from inferred domestic currency for MSISDN (FX / clearing review)"
  }
]
```

---

## 5. Settlement disputes

Matched Billing↔Roaming_Settlement pairs where |charged_amount − final_amount| exceeds tolerance (same signal as core approx_amount_mismatch).

**Count:** 15

```json
[
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "67",
    "cdr_id": "84",
    "Roaming_Settlement_record_id": 264,
    "Billing_final_amount": "27.42",
    "Roaming_Settlement_charged_amount": "27.92",
    "Roaming_Settlement_currency": "USD",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  },
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "79",
    "cdr_id": "99",
    "Roaming_Settlement_record_id": 396,
    "Billing_final_amount": "97.57",
    "Roaming_Settlement_charged_amount": "98.07",
    "Roaming_Settlement_currency": "USD",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  },
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "107",
    "cdr_id": "132",
    "Roaming_Settlement_record_id": 176,
    "Billing_final_amount": "119.96",
    "Roaming_Settlement_charged_amount": "120.46",
    "Roaming_Settlement_currency": "USD",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  },
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "152",
    "cdr_id": "186",
    "Roaming_Settlement_record_id": 616,
    "Billing_final_amount": "122.70",
    "Roaming_Settlement_charged_amount": "123.20",
    "Roaming_Settlement_currency": "INR",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  },
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "179",
    "cdr_id": "223",
    "Roaming_Settlement_record_id": 132,
    "Billing_final_amount": "25.28",
    "Roaming_Settlement_charged_amount": "25.78",
    "Roaming_Settlement_currency": "INR",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  },
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "275",
    "cdr_id": "356",
    "Roaming_Settlement_record_id": 572,
    "Billing_final_amount": "41.12",
    "Roaming_Settlement_charged_amount": "41.62",
    "Roaming_Settlement_currency": "USD",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  },
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "335",
    "cdr_id": "435",
    "Roaming_Settlement_record_id": 484,
    "Billing_final_amount": "40.70",
    "Roaming_Settlement_charged_amount": "41.20",
    "Roaming_Settlement_currency": "INR",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  },
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "339",
    "cdr_id": "440",
    "Roaming_Settlement_record_id": 352,
    "Billing_final_amount": "76.09",
    "Roaming_Settlement_charged_amount": "76.59",
    "Roaming_Settlement_currency": "EUR",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  },
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "443",
    "cdr_id": "570",
    "Roaming_Settlement_record_id": 528,
    "Billing_final_amount": "106.27",
    "Roaming_Settlement_charged_amount": "106.77",
    "Roaming_Settlement_currency": "USD",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  },
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "518",
    "cdr_id": "663",
    "Roaming_Settlement_record_id": 44,
    "Billing_final_amount": "125.26",
    "Roaming_Settlement_charged_amount": "125.76",
    "Roaming_Settlement_currency": "INR",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  },
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "534",
    "cdr_id": "683",
    "Roaming_Settlement_record_id": 440,
    "Billing_final_amount": "112.50",
    "Roaming_Settlement_charged_amount": "113.00",
    "Roaming_Settlement_currency": "AED",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  },
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "932",
    "cdr_id": "1205",
    "Roaming_Settlement_record_id": 308,
    "Billing_final_amount": "18.59",
    "Roaming_Settlement_charged_amount": "19.09",
    "Roaming_Settlement_currency": "INR",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  },
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "978",
    "cdr_id": "1252",
    "Roaming_Settlement_record_id": 220,
    "Billing_final_amount": "84.13",
    "Roaming_Settlement_charged_amount": "84.63",
    "Roaming_Settlement_currency": "GBP",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  },
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "986",
    "cdr_id": "1260",
    "Roaming_Settlement_record_id": 660,
    "Billing_final_amount": "129.27",
    "Roaming_Settlement_charged_amount": "129.77",
    "Roaming_Settlement_currency": "USD",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  },
  {
    "rule": "SETTLEMENT_AMOUNT_DISPUTE",
    "Billing_id": "1037",
    "cdr_id": "1311",
    "Roaming_Settlement_record_id": 88,
    "Billing_final_amount": "77.03",
    "Roaming_Settlement_charged_amount": "77.53",
    "Roaming_Settlement_currency": "INR",
    "abs_delta": "0.50",
    "detail": "Matched Roaming_Settlement partner charge differs materially from Billing final (settlement dispute signal)"
  }
]
```

---

## Matched pair sample (reference)

```json
[
  {
    "Billing_id": "1",
    "cdr_id": "1",
    "subscriber_id": "SUB-32181960",
    "Billing_final_amount": "88.51",
    "Billing_rating_timestamp": "2025-02-06 12:14:01",
    "Roaming_Settlement_record_id": 674,
    "Roaming_Settlement_charged_amount": "88.51",
    "Roaming_Settlement_currency": "GBP",
    "Roaming_Settlement_partner_code": "PRTARE1",
    "Roaming_Settlement_call_type": "MOC",
    "Roaming_Settlement_event_time": "2025-02-06 12:14:01",
    "Roaming_Settlement_duration_sec": 6074,
    "Roaming_Settlement_msisdn": "914332181960",
    "Roaming_Settlement_imsi": "404271643169580",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 0.0
  },
  {
    "Billing_id": "2",
    "cdr_id": "2",
    "subscriber_id": "SUB-41316475",
    "Billing_final_amount": "64.26",
    "Billing_rating_timestamp": "2025-02-10 10:12:56",
    "Roaming_Settlement_record_id": 197,
    "Roaming_Settlement_charged_amount": "64.26",
    "Roaming_Settlement_currency": "GBP",
    "Roaming_Settlement_partner_code": "PRTFRA3",
    "Roaming_Settlement_call_type": "GPRS",
    "Roaming_Settlement_event_time": "2025-02-10 10:05:56",
    "Roaming_Settlement_duration_sec": 569,
    "Roaming_Settlement_msisdn": "910341316475",
    "Roaming_Settlement_imsi": "404081927584827",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 420.0
  },
  {
    "Billing_id": "4",
    "cdr_id": "4",
    "subscriber_id": "SUB-17182278",
    "Billing_final_amount": "128.17",
    "Billing_rating_timestamp": "2025-02-03 20:16:15",
    "Roaming_Settlement_record_id": 489,
    "Roaming_Settlement_charged_amount": "128.17",
    "Roaming_Settlement_currency": "GBP",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "Roaming_Settlement_call_type": "MOC",
    "Roaming_Settlement_event_time": "2025-02-03 20:14:15",
    "Roaming_Settlement_duration_sec": 7192,
    "Roaming_Settlement_msisdn": "919117182278",
    "Roaming_Settlement_imsi": "404606576829967",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 120.0
  },
  {
    "Billing_id": "6",
    "cdr_id": "6",
    "subscriber_id": "SUB-68723430",
    "Billing_final_amount": "86.40",
    "Billing_rating_timestamp": "2025-02-19 23:31:27",
    "Roaming_Settlement_record_id": 683,
    "Roaming_Settlement_charged_amount": "86.40",
    "Roaming_Settlement_currency": "INR",
    "Roaming_Settlement_partner_code": "PRTARE1",
    "Roaming_Settlement_call_type": "GPRS",
    "Roaming_Settlement_event_time": "2025-02-19 23:21:27",
    "Roaming_Settlement_duration_sec": 6423,
    "Roaming_Settlement_msisdn": "917468723430",
    "Roaming_Settlement_imsi": "404634855002309",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 600.0
  },
  {
    "Billing_id": "8",
    "cdr_id": "8",
    "subscriber_id": "SUB-78680112",
    "Billing_final_amount": "78.38",
    "Billing_rating_timestamp": "2025-02-17 05:30:17",
    "Roaming_Settlement_record_id": 612,
    "Roaming_Settlement_charged_amount": "78.38",
    "Roaming_Settlement_currency": "INR",
    "Roaming_Settlement_partner_code": "PRTUK01",
    "Roaming_Settlement_call_type": "SMSMO",
    "Roaming_Settlement_event_time": "2025-02-17 05:29:17",
    "Roaming_Settlement_duration_sec": 1071,
    "Roaming_Settlement_msisdn": "914278680112",
    "Roaming_Settlement_imsi": "404710578703713",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 60.0
  },
  {
    "Billing_id": "9",
    "cdr_id": "10",
    "subscriber_id": "SUB-62994680",
    "Billing_final_amount": "132.96",
    "Billing_rating_timestamp": "2025-02-15 11:09:47",
    "Roaming_Settlement_record_id": 611,
    "Roaming_Settlement_charged_amount": "132.96",
    "Roaming_Settlement_currency": "USD",
    "Roaming_Settlement_partner_code": "PRTUK01",
    "Roaming_Settlement_call_type": "SMSMO",
    "Roaming_Settlement_event_time": "2025-02-15 11:06:47",
    "Roaming_Settlement_duration_sec": 1042,
    "Roaming_Settlement_msisdn": "913662994680",
    "Roaming_Settlement_imsi": "404615085511080",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 180.0
  },
  {
    "Billing_id": "10",
    "cdr_id": "11",
    "subscriber_id": "SUB-87083172",
    "Billing_final_amount": "32.89",
    "Billing_rating_timestamp": "2025-02-06 05:27:59",
    "Roaming_Settlement_record_id": 619,
    "Roaming_Settlement_charged_amount": "32.89",
    "Roaming_Settlement_currency": "EUR",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "Roaming_Settlement_call_type": "VOLTE",
    "Roaming_Settlement_event_time": "2025-02-06 05:22:59",
    "Roaming_Settlement_duration_sec": 3482,
    "Roaming_Settlement_msisdn": "913287083172",
    "Roaming_Settlement_imsi": "404200390291542",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 300.0
  },
  {
    "Billing_id": "11",
    "cdr_id": "12",
    "subscriber_id": "SUB-69096705",
    "Billing_final_amount": "62.35",
    "Billing_rating_timestamp": "2025-02-23 15:51:28",
    "Roaming_Settlement_record_id": 224,
    "Roaming_Settlement_charged_amount": "62.35",
    "Roaming_Settlement_currency": "AED",
    "Roaming_Settlement_partner_code": "PRTUK01",
    "Roaming_Settlement_call_type": "SMSMO",
    "Roaming_Settlement_event_time": "2025-02-23 15:49:28",
    "Roaming_Settlement_duration_sec": 510,
    "Roaming_Settlement_msisdn": "913669096705",
    "Roaming_Settlement_imsi": "404976748813914",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 120.0
  },
  {
    "Billing_id": "13",
    "cdr_id": "14",
    "subscriber_id": "SUB-67165726",
    "Billing_final_amount": "47.60",
    "Billing_rating_timestamp": "2025-02-19 00:11:46",
    "Roaming_Settlement_record_id": 415,
    "Roaming_Settlement_charged_amount": "47.60",
    "Roaming_Settlement_currency": "USD",
    "Roaming_Settlement_partner_code": "PRTARE1",
    "Roaming_Settlement_call_type": "MOC",
    "Roaming_Settlement_event_time": "2025-02-19 00:09:46",
    "Roaming_Settlement_duration_sec": 4144,
    "Roaming_Settlement_msisdn": "915067165726",
    "Roaming_Settlement_imsi": "404678689268551",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 120.0
  },
  {
    "Billing_id": "14",
    "cdr_id": "15",
    "subscriber_id": "SUB-77014363",
    "Billing_final_amount": "25.62",
    "Billing_rating_timestamp": "2025-02-20 19:33:23",
    "Roaming_Settlement_record_id": 175,
    "Roaming_Settlement_charged_amount": "25.62",
    "Roaming_Settlement_currency": "GBP",
    "Roaming_Settlement_partner_code": "PRTFRA3",
    "Roaming_Settlement_call_type": "GPRS",
    "Roaming_Settlement_event_time": "2025-02-20 19:32:23",
    "Roaming_Settlement_duration_sec": 4548,
    "Roaming_Settlement_msisdn": "913777014363",
    "Roaming_Settlement_imsi": "404368104636320",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 60.0
  },
  {
    "Billing_id": "15",
    "cdr_id": "17",
    "subscriber_id": "SUB-32812067",
    "Billing_final_amount": "77.86",
    "Billing_rating_timestamp": "2025-02-11 06:25:43",
    "Roaming_Settlement_record_id": 106,
    "Roaming_Settlement_charged_amount": "77.86",
    "Roaming_Settlement_currency": "GBP",
    "Roaming_Settlement_partner_code": "PRTUK01",
    "Roaming_Settlement_call_type": "MOC",
    "Roaming_Settlement_event_time": "2025-02-11 06:23:43",
    "Roaming_Settlement_duration_sec": 5410,
    "Roaming_Settlement_msisdn": "911232812067",
    "Roaming_Settlement_imsi": "404973840081105",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 120.0
  },
  {
    "Billing_id": "18",
    "cdr_id": "20",
    "subscriber_id": "SUB-27875588",
    "Billing_final_amount": "116.13",
    "Billing_rating_timestamp": "2025-02-15 13:35:33",
    "Roaming_Settlement_record_id": 302,
    "Roaming_Settlement_charged_amount": "116.13",
    "Roaming_Settlement_currency": "INR",
    "Roaming_Settlement_partner_code": "PRTDE02",
    "Roaming_Settlement_call_type": "SMSMO",
    "Roaming_Settlement_event_time": "2025-02-15 13:26:33",
    "Roaming_Settlement_duration_sec": 4808,
    "Roaming_Settlement_msisdn": "919727875588",
    "Roaming_Settlement_imsi": "404323291420417",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 540.0
  },
  {
    "Billing_id": "19",
    "cdr_id": "21",
    "subscriber_id": "SUB-09134316",
    "Billing_final_amount": "80.25",
    "Billing_rating_timestamp": "2025-02-16 09:30:13",
    "Roaming_Settlement_record_id": 260,
    "Roaming_Settlement_charged_amount": "80.25",
    "Roaming_Settlement_currency": "INR",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "Roaming_Settlement_call_type": "SMSMO",
    "Roaming_Settlement_event_time": "2025-02-16 09:21:13",
    "Roaming_Settlement_duration_sec": 5887,
    "Roaming_Settlement_msisdn": "917809134316",
    "Roaming_Settlement_imsi": "404114989216850",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 540.0
  },
  {
    "Billing_id": "20",
    "cdr_id": "22",
    "subscriber_id": "SUB-74367136",
    "Billing_final_amount": "32.63",
    "Billing_rating_timestamp": "2025-02-17 21:32:47",
    "Roaming_Settlement_record_id": 57,
    "Roaming_Settlement_charged_amount": "32.63",
    "Roaming_Settlement_currency": "AED",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "Roaming_Settlement_call_type": "VOLTE",
    "Roaming_Settlement_event_time": "2025-02-17 21:31:47",
    "Roaming_Settlement_duration_sec": 2450,
    "Roaming_Settlement_msisdn": "916474367136",
    "Roaming_Settlement_imsi": "404470130376049",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 60.0
  },
  {
    "Billing_id": "22",
    "cdr_id": "24",
    "subscriber_id": "SUB-92617964",
    "Billing_final_amount": "134.12",
    "Billing_rating_timestamp": "2025-02-19 02:29:35",
    "Roaming_Settlement_record_id": 531,
    "Roaming_Settlement_charged_amount": "134.12",
    "Roaming_Settlement_currency": "INR",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "Roaming_Settlement_call_type": "SMSMO",
    "Roaming_Settlement_event_time": "2025-02-19 02:21:35",
    "Roaming_Settlement_duration_sec": 6087,
    "Roaming_Settlement_msisdn": "918692617964",
    "Roaming_Settlement_imsi": "404771359923312",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 480.0
  },
  {
    "Billing_id": "23",
    "cdr_id": "25",
    "subscriber_id": "SUB-02053950",
    "Billing_final_amount": "29.10",
    "Billing_rating_timestamp": "2025-02-27 06:20:47",
    "Roaming_Settlement_record_id": 212,
    "Roaming_Settlement_charged_amount": "29.10",
    "Roaming_Settlement_currency": "GBP",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "Roaming_Settlement_call_type": "MTC",
    "Roaming_Settlement_event_time": "2025-02-27 06:13:47",
    "Roaming_Settlement_duration_sec": 6541,
    "Roaming_Settlement_msisdn": "912102053950",
    "Roaming_Settlement_imsi": "404981107808766",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 420.0
  },
  {
    "Billing_id": "24",
    "cdr_id": "26",
    "subscriber_id": "SUB-98478961",
    "Billing_final_amount": "119.20",
    "Billing_rating_timestamp": "2025-03-01 10:59:57",
    "Roaming_Settlement_record_id": 287,
    "Roaming_Settlement_charged_amount": "119.20",
    "Roaming_Settlement_currency": "GBP",
    "Roaming_Settlement_partner_code": "PRTFRA3",
    "Roaming_Settlement_call_type": "MOC",
    "Roaming_Settlement_event_time": "2025-03-01 10:49:57",
    "Roaming_Settlement_duration_sec": 5833,
    "Roaming_Settlement_msisdn": "915698478961",
    "Roaming_Settlement_imsi": "404221898701624",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 600.0
  },
  {
    "Billing_id": "26",
    "cdr_id": "29",
    "subscriber_id": "SUB-59696641",
    "Billing_final_amount": "84.20",
    "Billing_rating_timestamp": "2025-02-03 03:19:08",
    "Roaming_Settlement_record_id": 73,
    "Roaming_Settlement_charged_amount": "84.20",
    "Roaming_Settlement_currency": "AED",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "Roaming_Settlement_call_type": "VOLTE",
    "Roaming_Settlement_event_time": "2025-02-03 03:12:08",
    "Roaming_Settlement_duration_sec": 153,
    "Roaming_Settlement_msisdn": "917159696641",
    "Roaming_Settlement_imsi": "404357178620892",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 420.0
  },
  {
    "Billing_id": "29",
    "cdr_id": "32",
    "subscriber_id": "SUB-14188805",
    "Billing_final_amount": "103.75",
    "Billing_rating_timestamp": "2025-02-24 15:38:48",
    "Roaming_Settlement_record_id": 539,
    "Roaming_Settlement_charged_amount": "103.75",
    "Roaming_Settlement_currency": "GBP",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "Roaming_Settlement_call_type": "GPRS",
    "Roaming_Settlement_event_time": "2025-02-24 15:28:48",
    "Roaming_Settlement_duration_sec": 1855,
    "Roaming_Settlement_msisdn": "912214188805",
    "Roaming_Settlement_imsi": "404688238551510",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 600.0
  },
  {
    "Billing_id": "30",
    "cdr_id": "33",
    "subscriber_id": "SUB-41247826",
    "Billing_final_amount": "17.44",
    "Billing_rating_timestamp": "2025-02-19 02:35:36",
    "Roaming_Settlement_record_id": 501,
    "Roaming_Settlement_charged_amount": "17.44",
    "Roaming_Settlement_currency": "EUR",
    "Roaming_Settlement_partner_code": "PRTUSA2",
    "Roaming_Settlement_call_type": "GPRS",
    "Roaming_Settlement_event_time": "2025-02-19 02:34:36",
    "Roaming_Settlement_duration_sec": 840,
    "Roaming_Settlement_msisdn": "918141247826",
    "Roaming_Settlement_imsi": "404574205008000",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 60.0
  },
  {
    "Billing_id": "33",
    "cdr_id": "37",
    "subscriber_id": "SUB-68144739",
    "Billing_final_amount": "138.33",
    "Billing_rating_timestamp": "2025-02-02 08:00:28",
    "Roaming_Settlement_record_id": 453,
    "Roaming_Settlement_charged_amount": "138.33",
    "Roaming_Settlement_currency": "AED",
    "Roaming_Settlement_partner_code": "PRTDE02",
    "Roaming_Settlement_call_type": "GPRS",
    "Roaming_Settlement_event_time": "2025-02-02 07:51:28",
    "Roaming_Settlement_duration_sec": 1524,
    "Roaming_Settlement_msisdn": "917868144739",
    "Roaming_Settlement_imsi": "404778585991928",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 540.0
  },
  {
    "Billing_id": "34",
    "cdr_id": "38",
    "subscriber_id": "SUB-12517785",
    "Billing_final_amount": "86.07",
    "Billing_rating_timestamp": "2025-02-24 06:17:06",
    "Roaming_Settlement_record_id": 567,
    "Roaming_Settlement_charged_amount": "86.07",
    "Roaming_Settlement_currency": "INR",
    "Roaming_Settlement_partner_code": "PRTUK01",
    "Roaming_Settlement_call_type": "MOC",
    "Roaming_Settlement_event_time": "2025-02-24 06:10:06",
    "Roaming_Settlement_duration_sec": 3365,
    "Roaming_Settlement_msisdn": "916912517785",
    "Roaming_Settlement_imsi": "404824183356720",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 420.0
  },
  {
    "Billing_id": "35",
    "cdr_id": "39",
    "subscriber_id": "SUB-39690784",
    "Billing_final_amount": "15.46",
    "Billing_rating_timestamp": "2025-02-02 10:02:27",
    "Roaming_Settlement_record_id": 504,
    "Roaming_Settlement_charged_amount": "15.46",
    "Roaming_Settlement_currency": "AED",
    "Roaming_Settlement_partner_code": "PRTUK01",
    "Roaming_Settlement_call_type": "SMSMO",
    "Roaming_Settlement_event_time": "2025-02-02 10:00:27",
    "Roaming_Settlement_duration_sec": 372,
    "Roaming_Settlement_msisdn": "919439690784",
    "Roaming_Settlement_imsi": "404425922021395",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 120.0
  },
  {
    "Billing_id": "36",
    "cdr_id": "40",
    "subscriber_id": "SUB-95327877",
    "Billing_final_amount": "11.74",
    "Billing_rating_timestamp": "2025-03-02 23:03:00",
    "Roaming_Settlement_record_id": 64,
    "Roaming_Settlement_charged_amount": "11.74",
    "Roaming_Settlement_currency": "EUR",
    "Roaming_Settlement_partner_code": "PRTDE02",
    "Roaming_Settlement_call_type": "GPRS",
    "Roaming_Settlement_event_time": "2025-03-02 22:56:00",
    "Roaming_Settlement_duration_sec": 2033,
    "Roaming_Settlement_msisdn": "912595327877",
    "Roaming_Settlement_imsi": "404178027152273",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 420.0
  },
  {
    "Billing_id": "38",
    "cdr_id": "44",
    "subscriber_id": "SUB-77345401",
    "Billing_final_amount": "36.78",
    "Billing_rating_timestamp": "2025-02-07 18:49:38",
    "Roaming_Settlement_record_id": 432,
    "Roaming_Settlement_charged_amount": "36.78",
    "Roaming_Settlement_currency": "GBP",
    "Roaming_Settlement_partner_code": "PRTFRA3",
    "Roaming_Settlement_call_type": "MTC",
    "Roaming_Settlement_event_time": "2025-02-07 18:39:38",
    "Roaming_Settlement_duration_sec": 4508,
    "Roaming_Settlement_msisdn": "912677345401",
    "Roaming_Settlement_imsi": "404351006707603",
    "amount_abs_delta": 0.0,
    "time_delta_sec": 600.0
  }
]
```

---

## Core Billing → Roaming_Settlement metrics (reference)

```json
{
  "layer": "Billing \u2192 Roaming_Settlement",
  "Billing_total": 1200,
  "Roaming_Settlement_total": 1200,
  "Billing_rows_with_Roaming_Settlement_candidate": 696,
  "Roaming_Settlement_records_unmatched": 504,
  "approx_amount_mismatch_pairs": 15,
  "match_window_sec": 900,
  "samples": {
    "unmatched_tap": [
      {
        "tap_record_id": "697",
        "msisdn": "491686318552"
      },
      {
        "tap_record_id": "698",
        "msisdn": "494052426996"
      },
      {
        "tap_record_id": "699",
        "msisdn": "491379640497"
      },
      {
        "tap_record_id": "700",
        "msisdn": "497849082456"
      },
      {
        "tap_record_id": "701",
        "msisdn": "493571338447"
      },
      {
        "tap_record_id": "702",
        "msisdn": "496607664712"
      },
      {
        "tap_record_id": "703",
        "msisdn": "495832697360"
      },
      {
        "tap_record_id": "704",
        "msisdn": "492859683451"
      },
      {
        "tap_record_id": "705",
        "msisdn": "495883499605"
      },
      {
        "tap_record_id": "706",
        "msisdn": "496940948718"
      },
      {
        "tap_record_id": "707",
        "msisdn": "491870013651"
      },
      {
        "tap_record_id": "708",
        "msisdn": "496842122898"
      },
      {
        "tap_record_id": "709",
        "msisdn": "491531043080"
      },
      {
        "tap_record_id": "710",
        "msisdn": "493595184691"
      },
      {
        "tap_record_id": "711",
        "msisdn": "493333065597"
      },
      {
        "tap_record_id": "712",
        "msisdn": "492808551729"
      },
      {
        "tap_record_id": "713",
        "msisdn": "495640605643"
      },
      {
        "tap_record_id": "714",
        "msisdn": "496229822505"
      },
      {
        "tap_record_id": "715",
        "msisdn": "494462042457"
      },
      {
        "tap_record_id": "716",
        "msisdn": "497438572903"
      }
    ]
  }
}
```
