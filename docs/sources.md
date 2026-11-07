# Data sources, licenses and citations

Every source in data snapshot v1 (`data_snapshot_v1_2026-11-01`, built by
`scripts/ingest_data.py`). The URL, size, sha256 and fetch time of each file are in
`data/manifest.json` (1035 files: 1003 from physionet.org, 28 from wwwn.cdc.gov, 4 from GitHub).
Before submitting, check each PhysioNet project page for its exact required citation.

| Source | Version / pin | Where in data/ | Role | License |
|---|---|---|---|---|
| MIMIC-IV Clinical Database Demo | v1.0 | `raw/physionet/mimic_demo_v1_0`, schemas `mimic_demo_v1_0_*` | Messy source system; the version the OMOP ETL used | ODbL v1.0 (`LICENSE.txt` in folder) |
| MIMIC-IV Clinical Database Demo | v2.2 | `raw/physionet/mimic_demo_v2_2`, schemas `mimic_demo_v2_2_*` | Matches current MIMIC docs (v2.x) | ODbL v1.0 (`LICENSE.txt` in folder) |
| MIMIC-IV demo in the OMOP CDM | v0.9 (CDM 5.3.1) | `raw/physionet/omop_demo_v0_9`, schema `omop_demo_v0_9` | P2 mapping ground truth | ODbL v1.0 (`LICENSE.txt` in folder) |
| OHDSI/MIMIC ETL repo | commit `d209ed37` | `raw/github/omop_etl` | ETL SQL + `gcpt_*` concept mappings (finer-grained ground truth) | Apache 2.0 (`LICENSE` in folder) |
| NHANES 2017-2018 (CDC NCHS) | cycle suffix `_J`, 14 components | `raw/nhanes/2017-2018`, `docs/nhanes`, schema `nhanes_2017_2018` | Documentation-heavy source; P1 Q&A | Public domain (US government work) |
| MIMIC-IV documentation (MIT-LCP/mimic-website) | commit `81822278` | `docs/mimic` | RAG corpus (describes v2.x) | Not in snapshot; check the repo before citing |
| OMOP CDM v5.3 table/field specs (OHDSI/CommonDataModel) | commit `b90ae944` | `docs/omop` | RAG corpus | Not in snapshot; check the repo before citing |

NHANES components: DEMO, BMX, BPX, BPXO, GHB, GLU, TCHOL, HDL, TRIGLY, DIQ, BPQ, SMQ, MCQ,
RXQ_RX (data `.xpt` + codebook `.htm`). The full commit SHAs are in `scripts/ingest_data.py`.

ODbL allows redistribution with attribution, which is why the snapshot can be shared on the
team Drive (see `docs/DECISIONS.md`). The data stays out of git regardless.

## Citations
- Johnson, A., Bulgarelli, L., Pollard, T., Celi, L. A., Mark, R., & Horng, S. (2023).
  MIMIC-IV Clinical Database Demo (version 2.2). PhysioNet. https://doi.org/10.13026/dp1f-ex47
- MIMIC-IV Clinical Database Demo (version 1.0). PhysioNet. https://doi.org/10.13026/jwtp-v091
- Kallfelz, M., Tsvetkova, A., Pollard, T., Kwong, M., Lipori, G., Huser, V., Osborn, J., Hao,
  S., & Williams, A. (2021). MIMIC-IV demo data in the OMOP Common Data Model (version 0.9).
  PhysioNet.
- Goldberger, A., et al. (2000). PhysioBank, PhysioToolkit, and PhysioNet. Circulation 101(23).
- Centers for Disease Control and Prevention (CDC), National Center for Health Statistics.
  National Health and Nutrition Examination Survey Data, 2017-2018. Hyattsville, MD.
- MIT-LCP. MIMIC website and documentation. https://github.com/MIT-LCP/mimic-website
- OHDSI. MIMIC-IV to OMOP ETL. https://github.com/OHDSI/MIMIC
- OHDSI. OMOP Common Data Model v5.3. https://github.com/OHDSI/CommonDataModel
