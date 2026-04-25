# Mediation_billing_Reconciliation

_Generated: 2026-04-24T10:36:59.809894Z_
_Data directory: `/Users/algofusion/pythonProject1/pycharm_codes/CDR_DATA_SAMPLES`_

## Executive summary

| Detection area | Count |
|----------------|-------|
| Unrated usage (billable Mediation, no Billing row) | 24 |
| Not flagged for rating (rating_flag false) | 250 |
| Rating failures / integrity (incl. duplicate Billing cdr_id) | 123 |
| Incorrect tariff application (heuristic) | 151 |
| Bundle / discount / tax consistency | 0 |
| Zone / time-of-day heuristics | 78 |
| Corrupted Billing fields | 0 |
| Orphan Billing (cdr_id not in Mediation) | 0 |

---

## 1. Unrated usage events

Mediation rows with rating_flag true but no Billing row for that cdr_id (usage not billed).

**Count:** 24

Sample:

```json
[
  {
    "cdr_id": "65",
    "call_id": "CID-2024372-YJLC90",
    "subscriber_id": "SUB-38000307"
  },
  {
    "cdr_id": "182",
    "call_id": "CID-2024454-DADYMP",
    "subscriber_id": "SUB-83708164"
  },
  {
    "cdr_id": "246",
    "call_id": "CID-2024208-S127I3",
    "subscriber_id": "SUB-08830705"
  },
  {
    "cdr_id": "253",
    "call_id": "CID-2024062-3KEW9O",
    "subscriber_id": "SUB-43318751"
  },
  {
    "cdr_id": "275",
    "call_id": "CID-2024143-H01Z5D",
    "subscriber_id": "SUB-75534490"
  },
  {
    "cdr_id": "276",
    "call_id": "CID-2024411-SAYBAO",
    "subscriber_id": "SUB-12957860"
  },
  {
    "cdr_id": "301",
    "call_id": "CID-2024204-4YYCRY",
    "subscriber_id": "SUB-02909046"
  },
  {
    "cdr_id": "343",
    "call_id": "CID-2024750-T1QRMZ",
    "subscriber_id": "SUB-69507321"
  },
  {
    "cdr_id": "407",
    "call_id": "CID-2024559-Y24QCP",
    "subscriber_id": "SUB-00696801"
  },
  {
    "cdr_id": "450",
    "call_id": "CID-2024587-D7U8G6",
    "subscriber_id": "SUB-42551360"
  },
  {
    "cdr_id": "476",
    "call_id": "CID-2024848-ED18BE",
    "subscriber_id": "SUB-80142647"
  },
  {
    "cdr_id": "483",
    "call_id": "CID-2024419-ZAQVDX",
    "subscriber_id": "SUB-09662702"
  },
  {
    "cdr_id": "563",
    "call_id": "CID-2024585-EIWZWF",
    "subscriber_id": "SUB-71657893"
  },
  {
    "cdr_id": "591",
    "call_id": "CID-2024771-X0EF6Z",
    "subscriber_id": "SUB-09110349"
  },
  {
    "cdr_id": "626",
    "call_id": "CID-2024854-KDOR8B",
    "subscriber_id": "SUB-71564380"
  },
  {
    "cdr_id": "679",
    "call_id": "CID-2024296-BQFLF9",
    "subscriber_id": "SUB-44029363"
  },
  {
    "cdr_id": "709",
    "call_id": "CID-2024952-21LUM8",
    "subscriber_id": "SUB-42904957"
  },
  {
    "cdr_id": "714",
    "call_id": "CID-2024405-IGC4SF",
    "subscriber_id": "SUB-68593152"
  },
  {
    "cdr_id": "915",
    "call_id": "CID-2024875-FRPV8C",
    "subscriber_id": "SUB-54966025"
  },
  {
    "cdr_id": "922",
    "call_id": "CID-2024882-P4XASS",
    "subscriber_id": "SUB-08970649"
  },
  {
    "cdr_id": "1027",
    "call_id": "CID-2024785-412VXB",
    "subscriber_id": "SUB-21774911"
  },
  {
    "cdr_id": "1063",
    "call_id": "CID-2024646-J06RUQ",
    "subscriber_id": "SUB-47279392"
  },
  {
    "cdr_id": "1181",
    "call_id": "CID-2024109-VXKLYT",
    "subscriber_id": "SUB-05939670"
  },
  {
    "cdr_id": "1248",
    "call_id": "ORPH-MD-63-NT7N3",
    "subscriber_id": "SUB-83262250"
  }
]
```

### Not flagged for rating (context)

Mediation rows with rating_flag false (not eligible in demo pipeline; unrated by design).

**Count:** 250

```json
[
  {
    "cdr_id": "9",
    "call_id": "CID-2024339-BHQLQC",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "16",
    "call_id": "CID-2024451-VLDQ4H",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "27",
    "call_id": "CID-2024376-HRO199",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "35",
    "call_id": "CID-2024206-CMCUT6",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "41",
    "call_id": "CID-2024961-XJM6Z6",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "42",
    "call_id": "CID-2024174-7YJPCH",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "49",
    "call_id": "CID-2024094-8MDRYC",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "58",
    "call_id": "CID-2024187-XJ6Y0I",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "59",
    "call_id": "CID-2024760-596HHR",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "60",
    "call_id": "CID-2024283-IIPJUP",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "62",
    "call_id": "CID-2024792-IJE7AK",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "66",
    "call_id": "CID-2024651-AVAYTG",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "70",
    "call_id": "CID-2024616-OB74AV",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "76",
    "call_id": "CID-2024051-XMRX36",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "80",
    "call_id": "CID-2024909-IV5WMK",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "82",
    "call_id": "CID-2024336-W2RFXV",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "85",
    "call_id": "CID-2024986-5A7D91",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "87",
    "call_id": "CID-2024773-8MMS2L",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "92",
    "call_id": "CID-2024787-NC9Q88",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "102",
    "call_id": "CID-2024431-ZEFKVO",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "116",
    "call_id": "CID-2024093-H2XF7Y",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "123",
    "call_id": "CID-2024472-Z0PP9K",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "125",
    "call_id": "CID-2024147-51IFI0",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "130",
    "call_id": "CID-2024064-8T582B",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "133",
    "call_id": "CID-2024593-U0MUOH",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "135",
    "call_id": "CID-2024165-3B33IZ",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "137",
    "call_id": "CID-2024298-MEBO7V",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "152",
    "call_id": "CID-2024780-DL2IAZ",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "153",
    "call_id": "CID-2024614-QJFXKH",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "157",
    "call_id": "CID-2024522-10G3QW",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "159",
    "call_id": "CID-2024497-65OD7B",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "161",
    "call_id": "CID-2024645-HNXKS2",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "188",
    "call_id": "CID-2024451-GKFSFY",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "189",
    "call_id": "CID-2024451-GKFSFY",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "191",
    "call_id": "CID-2024174-FG1BKU",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "197",
    "call_id": "CID-2024889-ORAGYO",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "198",
    "call_id": "CID-2024723-3L2W36",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "204",
    "call_id": "CID-2024536-6BKRIS",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "211",
    "call_id": "CID-2024055-X1MRGG",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "214",
    "call_id": "CID-2024228-Y3FW33",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "219",
    "call_id": "CID-2024198-8PYQDR",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  },
  {
    "cdr_id": "220",
    "call_id": "CID-2024495-8AK7QH",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "227",
    "call_id": "CID-2024921-3JA41V",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "236",
    "call_id": "CID-2024512-TZD8H4",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "238",
    "call_id": "CID-2024672-EEQ8N5",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "243",
    "call_id": "CID-2024370-FW96EX",
    "mediation_status": "SUCCESS",
    "rating_flag": "False"
  },
  {
    "cdr_id": "248",
    "call_id": "CID-2024860-50PBSR",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "249",
    "call_id": "CID-2024370-8MK8ZO",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "256",
    "call_id": "CID-2024099-8RMBVU",
    "mediation_status": "QUARANTINE",
    "rating_flag": "False"
  },
  {
    "cdr_id": "261",
    "call_id": "CID-2024095-VYL1JS",
    "mediation_status": "REJECT_FORMAT",
    "rating_flag": "False"
  }
]
```

---

## 2. Rating failures

Non-POSTED Billing status, billed without rating_flag, non-SUCCESS Mediation, orphan Billing, duplicate cdr_id in Billing.

**Count:** 123

### 2a. Status / eligibility / orphan signals

```json
[
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "4",
    "cdr_id": "4",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "7",
    "cdr_id": "7",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "10",
    "cdr_id": "11",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "15",
    "cdr_id": "17",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "25",
    "cdr_id": "28",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "34",
    "cdr_id": "38",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "38",
    "cdr_id": "44",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "50",
    "cdr_id": "57",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "51",
    "cdr_id": "61",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "52",
    "cdr_id": "63",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "53",
    "cdr_id": "64",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "61",
    "cdr_id": "75",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "73",
    "cdr_id": "93",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "79",
    "cdr_id": "99",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "80",
    "cdr_id": "100",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "92",
    "cdr_id": "113",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "116",
    "cdr_id": "144",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "125",
    "cdr_id": "155",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "126",
    "cdr_id": "156",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "138",
    "cdr_id": "171",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "140",
    "cdr_id": "173",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "148",
    "cdr_id": "181",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "151",
    "cdr_id": "185",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "155",
    "cdr_id": "192",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "168",
    "cdr_id": "208",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "171",
    "cdr_id": "212",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "174",
    "cdr_id": "216",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "177",
    "cdr_id": "221",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "181",
    "cdr_id": "225",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "190",
    "cdr_id": "235",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "209",
    "cdr_id": "266",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "214",
    "cdr_id": "274",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "222",
    "cdr_id": "284",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "228",
    "cdr_id": "291",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "235",
    "cdr_id": "302",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "240",
    "cdr_id": "307",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "242",
    "cdr_id": "309",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "259",
    "cdr_id": "332",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "277",
    "cdr_id": "358",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "285",
    "cdr_id": "369",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "287",
    "cdr_id": "372",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "302",
    "cdr_id": "393",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "316",
    "cdr_id": "411",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "321",
    "cdr_id": "416",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "322",
    "cdr_id": "417",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "323",
    "cdr_id": "418",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "326",
    "cdr_id": "421",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "342",
    "cdr_id": "443",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "368",
    "cdr_id": "475",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "371",
    "cdr_id": "479",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "388",
    "cdr_id": "502",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "396",
    "cdr_id": "512",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "411",
    "cdr_id": "529",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "422",
    "cdr_id": "544",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "423",
    "cdr_id": "545",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "429",
    "cdr_id": "551",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "433",
    "cdr_id": "555",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "442",
    "cdr_id": "569",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_PENDING",
    "billing_id": "444",
    "cdr_id": "571",
    "billing_status": "PENDING_RATING",
    "detail": "Billing row exists but rating not completed"
  },
  {
    "rule": "RATING_FAILURE_DISPUTE_HOLD",
    "billing_id": "462",
    "cdr_id": "595",
    "billing_status": "DISPUTE_HOLD",
    "detail": "Rated amount on hold / dispute"
  }
]
```

### 2b. Duplicate Billing rows (same cdr_id)

```json
[]
```

---

## 3. Incorrect tariff application

Heuristic mismatch between Mediation service_type and tariff_plan_id (demo rules; includes DATA_5G on Voice/SMS).

**Count:** 151

```json
[
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 6,
    "billing_id": "6",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 19,
    "billing_id": "17",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 21,
    "billing_id": "19",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 36,
    "billing_id": "32",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 39,
    "billing_id": "35",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 46,
    "billing_id": "40",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 47,
    "billing_id": "41",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 48,
    "billing_id": "42",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 67,
    "billing_id": "54",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 72,
    "billing_id": "58",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 74,
    "billing_id": "60",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 81,
    "billing_id": "65",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 90,
    "billing_id": "71",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 97,
    "billing_id": "77",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 110,
    "billing_id": "89",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 129,
    "billing_id": "105",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 146,
    "billing_id": "118",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 155,
    "billing_id": "125",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 165,
    "billing_id": "132",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 166,
    "billing_id": "133",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 167,
    "billing_id": "134",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 176,
    "billing_id": "143",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 193,
    "billing_id": "156",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 195,
    "billing_id": "158",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 196,
    "billing_id": "159",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 209,
    "billing_id": "169",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 212,
    "billing_id": "171",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 216,
    "billing_id": "174",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 240,
    "billing_id": "193",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 260,
    "billing_id": "207",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 268,
    "billing_id": "211",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 287,
    "billing_id": "225",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 294,
    "billing_id": "230",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 303,
    "billing_id": "236",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 305,
    "billing_id": "238",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 315,
    "billing_id": "246",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 342,
    "billing_id": "267",
    "service_type": "Voice",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='Voice': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 359,
    "billing_id": "278",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 365,
    "billing_id": "283",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  },
  {
    "rule": "TARIFF_SERVICE_MISMATCH",
    "cdr_id": 369,
    "billing_id": "285",
    "service_type": "SMS",
    "tariff_plan_id": "DATA_5G",
    "detail": "plan not in allowed set for service_type='SMS': ['CORP_ENT', 'POST_UNL', 'PREP_STD', 'ROAM_ZONE1']"
  }
]
```

---

## 4. Bundle / discount errors

Tax not ~18% of rated_amount or discount not ~0 or 5% of rated (matches synthetic generator in generate_and_reconcile.py).

**Count:** 0

```json
[]
```

---

## 5. Zone / time-of-day mismatches

Rating timestamp before usage; ROAM_ZONE1 on domestic-like switch; large event vs rating hour divergence within short latency.

**Count:** 78

```json
[
  {
    "billing_id": "11",
    "cdr_id": 12,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "53",
    "cdr_id": 64,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "55",
    "cdr_id": 68,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "69",
    "cdr_id": 88,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "74",
    "cdr_id": 94,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "85",
    "cdr_id": 106,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "98",
    "cdr_id": 120,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "135",
    "cdr_id": 168,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "138",
    "cdr_id": 171,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "141",
    "cdr_id": 174,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "149",
    "cdr_id": 183,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "162",
    "cdr_id": 201,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "163",
    "cdr_id": 202,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "210",
    "cdr_id": 267,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "231",
    "cdr_id": 295,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "301",
    "cdr_id": 390,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "329",
    "cdr_id": 426,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "352",
    "cdr_id": 457,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "361",
    "cdr_id": 468,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "392",
    "cdr_id": 506,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "398",
    "cdr_id": 514,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "428",
    "cdr_id": 550,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "429",
    "cdr_id": 551,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "473",
    "cdr_id": 610,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "489",
    "cdr_id": 631,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "509",
    "cdr_id": 653,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "525",
    "cdr_id": 673,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "528",
    "cdr_id": 676,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "533",
    "cdr_id": 682,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "563",
    "cdr_id": 725,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "565",
    "cdr_id": 727,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "581",
    "cdr_id": 750,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "587",
    "cdr_id": 758,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "596",
    "cdr_id": 768,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "620",
    "cdr_id": 801,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "638",
    "cdr_id": 827,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "661",
    "cdr_id": 857,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "680",
    "cdr_id": 881,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "681",
    "cdr_id": 882,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-02 (demo: verify roam class vs domestic MSC)"
  },
  {
    "billing_id": "717",
    "cdr_id": 926,
    "rule": "ZONE_ROAM_PLAN_DOMESTIC_SWITCH",
    "detail": "ROAM_ZONE1 with source_switch=MSC-01 (demo: verify roam class vs domestic MSC)"
  }
]
```

---

## 6. Corrupted Billing fields

Required blanks, invalid amounts, arithmetic final != rated+tax-disc (Billing).

**Count:** 0

```json
[]
```

---

## Core Mediation → Billing metrics (reference)

```json
{
  "layer": "Mediation \u2192 Billing",
  "Mediation_total": 1474,
  "Billing_total": 1200,
  "Mediation_with_rating_flag": 1224,
  "Mediation_rated_in_billing": 1200,
  "unrated_usage_events": 24,
  "Mediation_rating_flag_false": 250,
  "Billing_rows_orphan_cdr": 0,
  "samples": {
    "unrated_eligible": [
      {
        "cdr_id": "65",
        "call_id": "CID-2024372-YJLC90"
      },
      {
        "cdr_id": "182",
        "call_id": "CID-2024454-DADYMP"
      },
      {
        "cdr_id": "246",
        "call_id": "CID-2024208-S127I3"
      },
      {
        "cdr_id": "253",
        "call_id": "CID-2024062-3KEW9O"
      },
      {
        "cdr_id": "275",
        "call_id": "CID-2024143-H01Z5D"
      },
      {
        "cdr_id": "276",
        "call_id": "CID-2024411-SAYBAO"
      },
      {
        "cdr_id": "301",
        "call_id": "CID-2024204-4YYCRY"
      },
      {
        "cdr_id": "343",
        "call_id": "CID-2024750-T1QRMZ"
      },
      {
        "cdr_id": "407",
        "call_id": "CID-2024559-Y24QCP"
      },
      {
        "cdr_id": "450",
        "call_id": "CID-2024587-D7U8G6"
      },
      {
        "cdr_id": "476",
        "call_id": "CID-2024848-ED18BE"
      },
      {
        "cdr_id": "483",
        "call_id": "CID-2024419-ZAQVDX"
      },
      {
        "cdr_id": "563",
        "call_id": "CID-2024585-EIWZWF"
      },
      {
        "cdr_id": "591",
        "call_id": "CID-2024771-X0EF6Z"
      },
      {
        "cdr_id": "626",
        "call_id": "CID-2024854-KDOR8B"
      },
      {
        "cdr_id": "679",
        "call_id": "CID-2024296-BQFLF9"
      },
      {
        "cdr_id": "709",
        "call_id": "CID-2024952-21LUM8"
      },
      {
        "cdr_id": "714",
        "call_id": "CID-2024405-IGC4SF"
      },
      {
        "cdr_id": "915",
        "call_id": "CID-2024875-FRPV8C"
      },
      {
        "cdr_id": "922",
        "call_id": "CID-2024882-P4XASS"
      }
    ],
    "rating_flag_false": [
      {
        "cdr_id": "9",
        "mediation_status": "QUARANTINE"
      },
      {
        "cdr_id": "16",
        "mediation_status": "REJECT_FORMAT"
      },
      {
        "cdr_id": "27",
        "mediation_status": "REJECT_FORMAT"
      },
      {
        "cdr_id": "35",
        "mediation_status": "SUCCESS"
      },
      {
        "cdr_id": "41",
        "mediation_status": "QUARANTINE"
      },
      {
        "cdr_id": "42",
        "mediation_status": "REJECT_FORMAT"
      },
      {
        "cdr_id": "49",
        "mediation_status": "SUCCESS"
      },
      {
        "cdr_id": "58",
        "mediation_status": "QUARANTINE"
      },
      {
        "cdr_id": "59",
        "mediation_status": "SUCCESS"
      },
      {
        "cdr_id": "60",
        "mediation_status": "SUCCESS"
      },
      {
        "cdr_id": "62",
        "mediation_status": "SUCCESS"
      },
      {
        "cdr_id": "66",
        "mediation_status": "REJECT_FORMAT"
      },
      {
        "cdr_id": "70",
        "mediation_status": "SUCCESS"
      },
      {
        "cdr_id": "76",
        "mediation_status": "SUCCESS"
      },
      {
        "cdr_id": "80",
        "mediation_status": "SUCCESS"
      }
    ],
    "orphan_billing": []
  }
}
```
