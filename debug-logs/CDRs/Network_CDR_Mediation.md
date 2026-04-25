# Network CDR and Mediation Reconciliation

_Generated: 2026-04-24T10:37:21.299480Z_
_Data directory: `/Users/algofusion/pythonProject1/pycharm_codes/CDR_DATA_SAMPLES`_

## Executive summary

| Detection area | Count |
|----------------|-------|
| Missing CDRs — not in Mediation (Network_CDR orphan) | 30 |
| Missing CDRs — not in Network_CDR (Mediation-only) | 290 |
| Duplicate records — Network_CDR (same call_id+msisdn+start) | 0 |
| Duplicate records — Mediation (key groups) | 14 |
| Corrupted fields — Network_CDR issues | 0 |
| Corrupted fields — Mediation issues | 0 |
| Timestamp mismatches (beyond tolerance) | 16 |
| Partial session loss signals (matched pairs) | 7 |

---

## 1. Missing CDRs

Records present in one layer but not aligned in the other (same call_id + MSISDN + time logic as core reconcile).

### 1a. Network_CDR records missing in Mediation

**Count:** 30

Sample (first 20):

```json
[
  {
    "Network_CDR_id": "113",
    "call_id": "CID-2024808-RD3AEY",
    "msisdn": "910698042043"
  },
  {
    "Network_CDR_id": "127",
    "call_id": "CID-2024483-E8TDV8",
    "msisdn": "912847818913"
  },
  {
    "Network_CDR_id": "159",
    "call_id": "CID-2024367-GX6M52",
    "msisdn": "916421476492"
  },
  {
    "Network_CDR_id": "288",
    "call_id": "CID-2024330-BHMT69",
    "msisdn": "916347557522"
  },
  {
    "Network_CDR_id": "330",
    "call_id": "CID-2024560-QNAEKC",
    "msisdn": "914023693626"
  },
  {
    "Network_CDR_id": "428",
    "call_id": "CID-2024338-V4A91F",
    "msisdn": "911375658963"
  },
  {
    "Network_CDR_id": "448",
    "call_id": "CID-2024700-EULH2T",
    "msisdn": "917873048625"
  },
  {
    "Network_CDR_id": "449",
    "call_id": "CID-2024588-BCHD89",
    "msisdn": "919946645099"
  },
  {
    "Network_CDR_id": "476",
    "call_id": "CID-2024789-Z7ZJ2L",
    "msisdn": "915726029254"
  },
  {
    "Network_CDR_id": "484",
    "call_id": "CID-2024162-8RUIRD",
    "msisdn": "910961730099"
  },
  {
    "Network_CDR_id": "492",
    "call_id": "CID-2024394-BSPX01",
    "msisdn": "912910845078"
  },
  {
    "Network_CDR_id": "498",
    "call_id": "CID-2024385-2AISPY",
    "msisdn": "910284976039"
  },
  {
    "Network_CDR_id": "526",
    "call_id": "CID-2024130-F74O7R",
    "msisdn": "913155505705"
  },
  {
    "Network_CDR_id": "528",
    "call_id": "CID-2024179-TFYXE9",
    "msisdn": "912915854233"
  },
  {
    "Network_CDR_id": "558",
    "call_id": "CID-2024209-N12YB6",
    "msisdn": "910848426483"
  },
  {
    "Network_CDR_id": "588",
    "call_id": "CID-2024740-9QUOGU",
    "msisdn": "918639945413"
  },
  {
    "Network_CDR_id": "635",
    "call_id": "CID-2024247-GH3LLZ",
    "msisdn": "913091401527"
  },
  {
    "Network_CDR_id": "725",
    "call_id": "CID-2024314-9OYQ7G",
    "msisdn": "912106378170"
  },
  {
    "Network_CDR_id": "729",
    "call_id": "CID-2024608-ZQV72Y",
    "msisdn": "910263276765"
  },
  {
    "Network_CDR_id": "865",
    "call_id": "CID-2024855-9CKI6B",
    "msisdn": "913418399557"
  }
]
```

### 1b. Mediation records missing in Network_CDR

**Count:** 290

Sample (first 20):

```json
[
  {
    "Mediation_id": "1185",
    "call_id": "ORPH-MD-0-049IR",
    "subscriber_id": "SUB-82000297"
  },
  {
    "Mediation_id": "1186",
    "call_id": "ORPH-MD-1-GZBNU",
    "subscriber_id": "SUB-09222212"
  },
  {
    "Mediation_id": "1187",
    "call_id": "ORPH-MD-2-ZD7N9",
    "subscriber_id": "SUB-27234424"
  },
  {
    "Mediation_id": "1188",
    "call_id": "ORPH-MD-3-L6T1Z",
    "subscriber_id": "SUB-89948223"
  },
  {
    "Mediation_id": "1189",
    "call_id": "ORPH-MD-4-O2ULF",
    "subscriber_id": "SUB-10818632"
  },
  {
    "Mediation_id": "1190",
    "call_id": "ORPH-MD-5-5QQKL",
    "subscriber_id": "SUB-47227004"
  },
  {
    "Mediation_id": "1191",
    "call_id": "ORPH-MD-6-2ROJD",
    "subscriber_id": "SUB-03748508"
  },
  {
    "Mediation_id": "1192",
    "call_id": "ORPH-MD-7-W725F",
    "subscriber_id": "SUB-30773667"
  },
  {
    "Mediation_id": "1193",
    "call_id": "ORPH-MD-8-SDU1S",
    "subscriber_id": "SUB-53837902"
  },
  {
    "Mediation_id": "1194",
    "call_id": "ORPH-MD-9-8CWKK",
    "subscriber_id": "SUB-78120796"
  },
  {
    "Mediation_id": "1195",
    "call_id": "ORPH-MD-10-BEH2U",
    "subscriber_id": "SUB-61737201"
  },
  {
    "Mediation_id": "1196",
    "call_id": "ORPH-MD-11-TTQ6C",
    "subscriber_id": "SUB-74735106"
  },
  {
    "Mediation_id": "1197",
    "call_id": "ORPH-MD-12-IOAA9",
    "subscriber_id": "SUB-78803024"
  },
  {
    "Mediation_id": "1198",
    "call_id": "ORPH-MD-13-O6AMX",
    "subscriber_id": "SUB-71550393"
  },
  {
    "Mediation_id": "1199",
    "call_id": "ORPH-MD-14-8G85X",
    "subscriber_id": "SUB-31295048"
  },
  {
    "Mediation_id": "1200",
    "call_id": "ORPH-MD-15-8ZNGC",
    "subscriber_id": "SUB-27809928"
  },
  {
    "Mediation_id": "1201",
    "call_id": "ORPH-MD-16-EQ8Z4",
    "subscriber_id": "SUB-78630381"
  },
  {
    "Mediation_id": "1202",
    "call_id": "ORPH-MD-17-FCGVQ",
    "subscriber_id": "SUB-86444911"
  },
  {
    "Mediation_id": "1203",
    "call_id": "ORPH-MD-18-6TLOB",
    "subscriber_id": "SUB-73018087"
  },
  {
    "Mediation_id": "1204",
    "call_id": "ORPH-MD-19-HROSE",
    "subscriber_id": "SUB-75215272"
  }
]
```

---

## 2. Duplicate records

Duplicate Network_CDR keys and duplicate Mediation key groups.

### 2a. Duplicate Network_CDR keys

**Groups:** 0

```json
[]
```

### 2b. Duplicate Mediation groups (cdr_id lists)

**Groups:** 14

```json
[
  [
    1086,
    1087
  ],
  [
    1102,
    1103
  ],
  [
    695,
    696
  ],
  [
    283,
    284
  ],
  [
    356,
    357
  ],
  [
    690,
    691
  ],
  [
    548,
    549
  ],
  [
    422,
    423
  ],
  [
    188,
    189
  ],
  [
    277,
    278
  ],
  [
    304,
    305
  ],
  [
    851,
    852
  ],
  [
    857,
    858
  ],
  [
    561,
    562
  ]
]
```

---

## 3. Corrupted fields

Required fields blank, unparseable timestamps, invalid session window, duration anomalies.

### 3a. Network_CDR

**Issues:** 0

```json
[]
```

### 3b. Mediation

**Issues:** 0

```json
[]
```

---

## 4. Timestamp mismatches

Mediation event vs best Network_CDR start exceeds tolerance (still linked).

Tolerance used: **30** seconds.

**Count:** 16

```json
[
  {
    "Network_CDR_id": "1",
    "Mediation_id": "1",
    "delta_sec": 35.0,
    "nw_call_start": "2025-02-06 09:42:36",
    "md_event_timestamp": "2025-02-06 09:42:01"
  },
  {
    "Network_CDR_id": "78",
    "Mediation_id": "78",
    "delta_sec": 40.0,
    "nw_call_start": "2025-02-21 07:39:51",
    "md_event_timestamp": "2025-02-21 07:40:31"
  },
  {
    "Network_CDR_id": "155",
    "Mediation_id": "153",
    "delta_sec": 40.0,
    "nw_call_start": "2025-02-28 02:44:04",
    "md_event_timestamp": "2025-02-28 02:44:44"
  },
  {
    "Network_CDR_id": "232",
    "Mediation_id": "230",
    "delta_sec": 35.0,
    "nw_call_start": "2025-02-23 23:17:31",
    "md_event_timestamp": "2025-02-23 23:16:56"
  },
  {
    "Network_CDR_id": "309",
    "Mediation_id": "309",
    "delta_sec": 40.0,
    "nw_call_start": "2025-02-16 07:18:52",
    "md_event_timestamp": "2025-02-16 07:19:32"
  },
  {
    "Network_CDR_id": "386",
    "Mediation_id": "386",
    "delta_sec": 40.0,
    "nw_call_start": "2025-03-02 14:29:50",
    "md_event_timestamp": "2025-03-02 14:30:30"
  },
  {
    "Network_CDR_id": "463",
    "Mediation_id": "461",
    "delta_sec": 35.0,
    "nw_call_start": "2025-02-06 18:46:27",
    "md_event_timestamp": "2025-02-06 18:45:52"
  },
  {
    "Network_CDR_id": "540",
    "Mediation_id": "532",
    "delta_sec": 35.0,
    "nw_call_start": "2025-02-11 17:06:12",
    "md_event_timestamp": "2025-02-11 17:05:37"
  },
  {
    "Network_CDR_id": "617",
    "Mediation_id": "609",
    "delta_sec": 35.0,
    "nw_call_start": "2025-02-27 08:38:10",
    "md_event_timestamp": "2025-02-27 08:37:35"
  },
  {
    "Network_CDR_id": "694",
    "Mediation_id": "685",
    "delta_sec": 40.0,
    "nw_call_start": "2025-02-24 20:09:56",
    "md_event_timestamp": "2025-02-24 20:10:36"
  },
  {
    "Network_CDR_id": "771",
    "Mediation_id": "762",
    "delta_sec": 35.0,
    "nw_call_start": "2025-02-04 22:32:48",
    "md_event_timestamp": "2025-02-04 22:32:13"
  },
  {
    "Network_CDR_id": "848",
    "Mediation_id": "839",
    "delta_sec": 40.0,
    "nw_call_start": "2025-02-13 11:17:57",
    "md_event_timestamp": "2025-02-13 11:18:37"
  },
  {
    "Network_CDR_id": "925",
    "Mediation_id": "914",
    "delta_sec": 40.0,
    "nw_call_start": "2025-02-16 16:40:16",
    "md_event_timestamp": "2025-02-16 16:40:56"
  },
  {
    "Network_CDR_id": "1002",
    "Mediation_id": "988",
    "delta_sec": 40.0,
    "nw_call_start": "2025-02-02 05:03:23",
    "md_event_timestamp": "2025-02-02 05:04:03"
  },
  {
    "Network_CDR_id": "1079",
    "Mediation_id": "1064",
    "delta_sec": 35.0,
    "nw_call_start": "2025-02-11 02:10:10",
    "md_event_timestamp": "2025-02-11 02:09:35"
  },
  {
    "Network_CDR_id": "1156",
    "Mediation_id": "1140",
    "delta_sec": 40.0,
    "nw_call_start": "2025-02-06 13:21:15",
    "md_event_timestamp": "2025-02-06 13:21:55"
  }
]
```

---

## 5. Partial session losses

Matched pairs where duration diverges beyond threshold or Mediation event falls outside Network_CDR start/end.

**Count:** 7

```json
[
  {
    "rule": "PARTIAL_SESSION_EVENT_OUTSIDE_WINDOW",
    "Network_CDR_id": "1",
    "Mediation_id": "1",
    "detail": "Mediation event_timestamp outside Network_CDR [start,end]; delta_sec_vs_start=-35"
  },
  {
    "rule": "PARTIAL_SESSION_EVENT_OUTSIDE_WINDOW",
    "Network_CDR_id": "232",
    "Mediation_id": "230",
    "detail": "Mediation event_timestamp outside Network_CDR [start,end]; delta_sec_vs_start=-35"
  },
  {
    "rule": "PARTIAL_SESSION_EVENT_OUTSIDE_WINDOW",
    "Network_CDR_id": "463",
    "Mediation_id": "461",
    "detail": "Mediation event_timestamp outside Network_CDR [start,end]; delta_sec_vs_start=-35"
  },
  {
    "rule": "PARTIAL_SESSION_EVENT_OUTSIDE_WINDOW",
    "Network_CDR_id": "540",
    "Mediation_id": "532",
    "detail": "Mediation event_timestamp outside Network_CDR [start,end]; delta_sec_vs_start=-35"
  },
  {
    "rule": "PARTIAL_SESSION_EVENT_OUTSIDE_WINDOW",
    "Network_CDR_id": "617",
    "Mediation_id": "609",
    "detail": "Mediation event_timestamp outside Network_CDR [start,end]; delta_sec_vs_start=-35"
  },
  {
    "rule": "PARTIAL_SESSION_EVENT_OUTSIDE_WINDOW",
    "Network_CDR_id": "771",
    "Mediation_id": "762",
    "detail": "Mediation event_timestamp outside Network_CDR [start,end]; delta_sec_vs_start=-35"
  },
  {
    "rule": "PARTIAL_SESSION_EVENT_OUTSIDE_WINDOW",
    "Network_CDR_id": "1079",
    "Mediation_id": "1064",
    "detail": "Mediation event_timestamp outside Network_CDR [start,end]; delta_sec_vs_start=-35"
  }
]
```

---

## Core reconciliation metrics (reference)

```json
{
  "layer": "Network_CDR \u2192 Mediation",
  "tolerance_sec": 30,
  "Network_CDR_total": 1200,
  "Mediation_total": 1474,
  "matched_pairs_estimate": 1184,
  "missing_in_mediation_count": 30,
  "missing_in_network_count": 290,
  "timestamp_mismatch_count": 16,
  "Mediation_duplicate_groups": 14,
  "samples": {
    "missing_in_mediation": [
      {
        "Network_CDR_id": "113",
        "call_id": "CID-2024808-RD3AEY",
        "msisdn": "910698042043"
      },
      {
        "Network_CDR_id": "127",
        "call_id": "CID-2024483-E8TDV8",
        "msisdn": "912847818913"
      },
      {
        "Network_CDR_id": "159",
        "call_id": "CID-2024367-GX6M52",
        "msisdn": "916421476492"
      },
      {
        "Network_CDR_id": "288",
        "call_id": "CID-2024330-BHMT69",
        "msisdn": "916347557522"
      },
      {
        "Network_CDR_id": "330",
        "call_id": "CID-2024560-QNAEKC",
        "msisdn": "914023693626"
      },
      {
        "Network_CDR_id": "428",
        "call_id": "CID-2024338-V4A91F",
        "msisdn": "911375658963"
      },
      {
        "Network_CDR_id": "448",
        "call_id": "CID-2024700-EULH2T",
        "msisdn": "917873048625"
      },
      {
        "Network_CDR_id": "449",
        "call_id": "CID-2024588-BCHD89",
        "msisdn": "919946645099"
      },
      {
        "Network_CDR_id": "476",
        "call_id": "CID-2024789-Z7ZJ2L",
        "msisdn": "915726029254"
      },
      {
        "Network_CDR_id": "484",
        "call_id": "CID-2024162-8RUIRD",
        "msisdn": "910961730099"
      },
      {
        "Network_CDR_id": "492",
        "call_id": "CID-2024394-BSPX01",
        "msisdn": "912910845078"
      },
      {
        "Network_CDR_id": "498",
        "call_id": "CID-2024385-2AISPY",
        "msisdn": "910284976039"
      },
      {
        "Network_CDR_id": "526",
        "call_id": "CID-2024130-F74O7R",
        "msisdn": "913155505705"
      },
      {
        "Network_CDR_id": "528",
        "call_id": "CID-2024179-TFYXE9",
        "msisdn": "912915854233"
      },
      {
        "Network_CDR_id": "558",
        "call_id": "CID-2024209-N12YB6",
        "msisdn": "910848426483"
      }
    ],
    "missing_in_network": [
      {
        "Mediation_id": "1185",
        "call_id": "ORPH-MD-0-049IR",
        "subscriber_id": "SUB-82000297"
      },
      {
        "Mediation_id": "1186",
        "call_id": "ORPH-MD-1-GZBNU",
        "subscriber_id": "SUB-09222212"
      },
      {
        "Mediation_id": "1187",
        "call_id": "ORPH-MD-2-ZD7N9",
        "subscriber_id": "SUB-27234424"
      },
      {
        "Mediation_id": "1188",
        "call_id": "ORPH-MD-3-L6T1Z",
        "subscriber_id": "SUB-89948223"
      },
      {
        "Mediation_id": "1189",
        "call_id": "ORPH-MD-4-O2ULF",
        "subscriber_id": "SUB-10818632"
      },
      {
        "Mediation_id": "1190",
        "call_id": "ORPH-MD-5-5QQKL",
        "subscriber_id": "SUB-47227004"
      },
      {
        "Mediation_id": "1191",
        "call_id": "ORPH-MD-6-2ROJD",
        "subscriber_id": "SUB-03748508"
      },
      {
        "Mediation_id": "1192",
        "call_id": "ORPH-MD-7-W725F",
        "subscriber_id": "SUB-30773667"
      },
      {
        "Mediation_id": "1193",
        "call_id": "ORPH-MD-8-SDU1S",
        "subscriber_id": "SUB-53837902"
      },
      {
        "Mediation_id": "1194",
        "call_id": "ORPH-MD-9-8CWKK",
        "subscriber_id": "SUB-78120796"
      },
      {
        "Mediation_id": "1195",
        "call_id": "ORPH-MD-10-BEH2U",
        "subscriber_id": "SUB-61737201"
      },
      {
        "Mediation_id": "1196",
        "call_id": "ORPH-MD-11-TTQ6C",
        "subscriber_id": "SUB-74735106"
      },
      {
        "Mediation_id": "1197",
        "call_id": "ORPH-MD-12-IOAA9",
        "subscriber_id": "SUB-78803024"
      },
      {
        "Mediation_id": "1198",
        "call_id": "ORPH-MD-13-O6AMX",
        "subscriber_id": "SUB-71550393"
      },
      {
        "Mediation_id": "1199",
        "call_id": "ORPH-MD-14-8G85X",
        "subscriber_id": "SUB-31295048"
      }
    ],
    "timestamp_mismatches": [
      {
        "Network_CDR_id": "1",
        "Mediation_id": "1",
        "delta_sec": 35.0,
        "nw_call_start": "2025-02-06 09:42:36",
        "md_event_timestamp": "2025-02-06 09:42:01"
      },
      {
        "Network_CDR_id": "78",
        "Mediation_id": "78",
        "delta_sec": 40.0,
        "nw_call_start": "2025-02-21 07:39:51",
        "md_event_timestamp": "2025-02-21 07:40:31"
      },
      {
        "Network_CDR_id": "155",
        "Mediation_id": "153",
        "delta_sec": 40.0,
        "nw_call_start": "2025-02-28 02:44:04",
        "md_event_timestamp": "2025-02-28 02:44:44"
      },
      {
        "Network_CDR_id": "232",
        "Mediation_id": "230",
        "delta_sec": 35.0,
        "nw_call_start": "2025-02-23 23:17:31",
        "md_event_timestamp": "2025-02-23 23:16:56"
      },
      {
        "Network_CDR_id": "309",
        "Mediation_id": "309",
        "delta_sec": 40.0,
        "nw_call_start": "2025-02-16 07:18:52",
        "md_event_timestamp": "2025-02-16 07:19:32"
      },
      {
        "Network_CDR_id": "386",
        "Mediation_id": "386",
        "delta_sec": 40.0,
        "nw_call_start": "2025-03-02 14:29:50",
        "md_event_timestamp": "2025-03-02 14:30:30"
      },
      {
        "Network_CDR_id": "463",
        "Mediation_id": "461",
        "delta_sec": 35.0,
        "nw_call_start": "2025-02-06 18:46:27",
        "md_event_timestamp": "2025-02-06 18:45:52"
      },
      {
        "Network_CDR_id": "540",
        "Mediation_id": "532",
        "delta_sec": 35.0,
        "nw_call_start": "2025-02-11 17:06:12",
        "md_event_timestamp": "2025-02-11 17:05:37"
      },
      {
        "Network_CDR_id": "617",
        "Mediation_id": "609",
        "delta_sec": 35.0,
        "nw_call_start": "2025-02-27 08:38:10",
        "md_event_timestamp": "2025-02-27 08:37:35"
      },
      {
        "Network_CDR_id": "694",
        "Mediation_id": "685",
        "delta_sec": 40.0,
        "nw_call_start": "2025-02-24 20:09:56",
        "md_event_timestamp": "2025-02-24 20:10:36"
      },
      {
        "Network_CDR_id": "771",
        "Mediation_id": "762",
        "delta_sec": 35.0,
        "nw_call_start": "2025-02-04 22:32:48",
        "md_event_timestamp": "2025-02-04 22:32:13"
      },
      {
        "Network_CDR_id": "848",
        "Mediation_id": "839",
        "delta_sec": 40.0,
        "nw_call_start": "2025-02-13 11:17:57",
        "md_event_timestamp": "2025-02-13 11:18:37"
      },
      {
        "Network_CDR_id": "925",
        "Mediation_id": "914",
        "delta_sec": 40.0,
        "nw_call_start": "2025-02-16 16:40:16",
        "md_event_timestamp": "2025-02-16 16:40:56"
      },
      {
        "Network_CDR_id": "1002",
        "Mediation_id": "988",
        "delta_sec": 40.0,
        "nw_call_start": "2025-02-02 05:03:23",
        "md_event_timestamp": "2025-02-02 05:04:03"
      },
      {
        "Network_CDR_id": "1079",
        "Mediation_id": "1064",
        "delta_sec": 35.0,
        "nw_call_start": "2025-02-11 02:10:10",
        "md_event_timestamp": "2025-02-11 02:09:35"
      }
    ],
    "duplicate_groups": [
      [
        1086,
        1087
      ],
      [
        1102,
        1103
      ],
      [
        695,
        696
      ],
      [
        283,
        284
      ],
      [
        356,
        357
      ],
      [
        690,
        691
      ],
      [
        548,
        549
      ],
      [
        422,
        423
      ],
      [
        188,
        189
      ],
      [
        277,
        278
      ]
    ]
  }
}
```
