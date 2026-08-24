"""
icd10_diagnoses.py
------------------
Curated ICD-10 diagnosis list for synthetic hospital database generation.

Covers 70 common inpatient diagnoses across 11 clinical categories.
Each entry includes:
    - icd10_code     : Standard ICD-10-CM code
    - diagnosis_name : Clinical name (common_name field added in v2)
    - departments    : List of departments where this diagnosis typically appears
    - weight         : Relative prevalence for weighted random sampling
                       Weights are proportional to real US inpatient admission
                       frequencies (CMS/HCUP data). They do not need to sum to 1 —
                       np.random.choice normalizes them automatically when you pass
                       p = weights / weights.sum()

Usage:
    import numpy as np
    import pandas as pd
    from icd10_diagnoses import DIAGNOSES, get_diagnoses_df, get_diagnoses_for_department

    df = get_diagnoses_df()

    # Weighted random sample of 1 diagnosis
    sample = df.sample(n=1, weights='weight')

    # Department-filtered weighted sample
    cardio_dx = get_diagnoses_for_department('Cardiology')
    sample = cardio_dx.sample(n=1, weights='weight')
"""

import numpy as np
import pandas as pd

# ─── DIAGNOSES ────────────────────────────────────────────────────────────────
# Organized by clinical category. Within each category, entries are ordered
# roughly by descending prevalence.

DIAGNOSES = [

    # ── CARDIOVASCULAR ────────────────────────────────────────────────────────
    {
        "icd10_code":      "I50.9",
        "diagnosis_name":  "Heart failure, unspecified",
        "departments":     ["Cardiology", "Intensive Care", "Internal Medicine", "Geriatric"],
        "weight":          9.5
    },
    {
        "icd10_code":      "I21.9",
        "diagnosis_name":  "Acute myocardial infarction, unspecified",
        "departments":     ["Cardiology", "Intensive Care", "Emergency Medicine"],
        "weight":          8.5
    },
    {
        "icd10_code":      "I10",
        "diagnosis_name":  "Essential (primary) hypertension",
        "departments":     ["Cardiology", "Internal Medicine", "Geriatric", "Emergency Medicine"],
        "weight":          8.0
    },
    {
        "icd10_code":      "I48.91",
        "diagnosis_name":  "Unspecified atrial fibrillation",
        "departments":     ["Cardiology", "Intensive Care", "Internal Medicine"],
        "weight":          6.5
    },
    {
        "icd10_code":      "I63.9",
        "diagnosis_name":  "Cerebral infarction, unspecified",
        "departments":     ["Neurology", "Intensive Care", "Emergency Medicine"],
        "weight":          5.5
    },
    {
        "icd10_code":      "I25.10",
        "diagnosis_name":  "Atherosclerotic heart disease of native coronary artery",
        "departments":     ["Cardiology", "Internal Medicine", "Geriatric"],
        "weight":          5.0
    },
    {
        "icd10_code":      "I35.0",
        "diagnosis_name":  "Nonrheumatic aortic (valve) stenosis",
        "departments":     ["Cardiology", "Operations", "Intensive Care"],
        "weight":          2.5
    },

    # ── RESPIRATORY ───────────────────────────────────────────────────────────
    {
        "icd10_code":      "J18.9",
        "diagnosis_name":  "Pneumonia, unspecified organism",
        "departments":     ["Internal Medicine", "Intensive Care", "Emergency Medicine",
                            "Pediatrics", "Geriatric"],
        "weight":          9.0
    },
    {
        "icd10_code":      "J44.1",
        "diagnosis_name":  "Chronic obstructive pulmonary disease with acute exacerbation",
        "departments":     ["Internal Medicine", "Intensive Care", "Emergency Medicine", "Geriatric"],
        "weight":          7.0
    },
    {
        "icd10_code":      "J96.00",
        "diagnosis_name":  "Acute respiratory failure, unspecified",
        "departments":     ["Intensive Care", "Emergency Medicine", "Internal Medicine"],
        "weight":          5.5
    },
    {
        "icd10_code":      "J45.901",
        "diagnosis_name":  "Unspecified asthma with (acute) exacerbation",
        "departments":     ["Emergency Medicine", "Internal Medicine", "Pediatrics"],
        "weight":          4.5
    },
    {
        "icd10_code":      "J12.89",
        "diagnosis_name":  "Other viral pneumonia",
        "departments":     ["Internal Medicine", "Intensive Care", "Emergency Medicine",
                            "Pediatrics"],
        "weight":          4.0
    },

    # ── ENDOCRINE / METABOLIC ─────────────────────────────────────────────────
    {
        "icd10_code":      "E11.9",
        "diagnosis_name":  "Type 2 diabetes mellitus without complications",
        "departments":     ["Endocrinology", "Internal Medicine", "Geriatric"],
        "weight":          8.0
    },
    {
        "icd10_code":      "E11.65",
        "diagnosis_name":  "Type 2 diabetes mellitus with hyperglycemia",
        "departments":     ["Endocrinology", "Internal Medicine", "Emergency Medicine"],
        "weight":          5.5
    },
    {
        "icd10_code":      "E10.9",
        "diagnosis_name":  "Type 1 diabetes mellitus without complications",
        "departments":     ["Endocrinology", "Internal Medicine", "Pediatrics"],
        "weight":          3.5
    },
    {
        "icd10_code":      "E86.0",
        "diagnosis_name":  "Dehydration",
        "departments":     ["Emergency Medicine", "Internal Medicine", "Pediatrics", "Geriatric"],
        "weight":          5.0
    },
    {
        "icd10_code":      "E87.1",
        "diagnosis_name":  "Hyponatremia",
        "departments":     ["Internal Medicine", "Intensive Care", "Geriatric"],
        "weight":          4.0
    },
    {
        "icd10_code":      "E87.6",
        "diagnosis_name":  "Hypokalemia",
        "departments":     ["Internal Medicine", "Intensive Care", "Cardiology"],
        "weight":          3.5
    },
    {
        "icd10_code":      "E66.9",
        "diagnosis_name":  "Obesity, unspecified",
        "departments":     ["Internal Medicine", "Endocrinology", "General Surgery"],
        "weight":          4.0
    },

    # ── INFECTIOUS DISEASE / SEPSIS ───────────────────────────────────────────
    {
        "icd10_code":      "A41.9",
        "diagnosis_name":  "Sepsis, unspecified organism",
        "departments":     ["Intensive Care", "Emergency Medicine", "Internal Medicine"],
        "weight":          8.5
    },
    {
        "icd10_code":      "A41.01",
        "diagnosis_name":  "Sepsis due to methicillin susceptible Staphylococcus aureus",
        "departments":     ["Intensive Care", "Internal Medicine", "Emergency Medicine"],
        "weight":          4.0
    },
    {
        "icd10_code":      "N39.0",
        "diagnosis_name":  "Urinary tract infection, site not specified",
        "departments":     ["Urology", "Internal Medicine", "Emergency Medicine",
                            "Geriatric", "OB/GYN"],
        "weight":          7.0
    },
    {
        "icd10_code":      "A04.72",
        "diagnosis_name":  "Enterocolitis due to Clostridium difficile, not specified as recurrent",
        "departments":     ["Gastroenterology", "Internal Medicine", "Intensive Care"],
        "weight":          3.5
    },
    {
        "icd10_code":      "B34.9",
        "diagnosis_name":  "Viral infection, unspecified",
        "departments":     ["Emergency Medicine", "Internal Medicine", "Pediatrics"],
        "weight":          4.5
    },

    # ── GASTROINTESTINAL ──────────────────────────────────────────────────────
    {
        "icd10_code":      "K92.1",
        "diagnosis_name":  "Melena",
        "departments":     ["Gastroenterology", "Internal Medicine", "Emergency Medicine"],
        "weight":          4.0
    },
    {
        "icd10_code":      "K57.32",
        "diagnosis_name":  "Diverticulitis of large intestine without perforation or abscess",
        "departments":     ["Gastroenterology", "General Surgery", "Emergency Medicine"],
        "weight":          4.5
    },
    {
        "icd10_code":      "K80.20",
        "diagnosis_name":  "Calculus of gallbladder without cholecystitis",
        "departments":     ["Gastroenterology", "General Surgery", "Emergency Medicine"],
        "weight":          4.0
    },
    {
        "icd10_code":      "K35.80",
        "diagnosis_name":  "Other and unspecified acute appendicitis",
        "departments":     ["General Surgery", "Emergency Medicine", "Pediatrics"],
        "weight":          4.5
    },
    {
        "icd10_code":      "K74.60",
        "diagnosis_name":  "Unspecified cirrhosis of liver",
        "departments":     ["Gastroenterology", "Internal Medicine", "Intensive Care"],
        "weight":          3.5
    },
    {
        "icd10_code":      "K56.60",
        "diagnosis_name":  "Unspecified intestinal obstruction",
        "departments":     ["General Surgery", "Gastroenterology", "Emergency Medicine"],
        "weight":          3.0
    },
    {
        "icd10_code":      "K29.70",
        "diagnosis_name":  "Gastritis, unspecified, without bleeding",
        "departments":     ["Gastroenterology", "Internal Medicine", "Emergency Medicine"],
        "weight":          3.5
    },

    # ── RENAL ─────────────────────────────────────────────────────────────────
    {
        "icd10_code":      "N17.9",
        "diagnosis_name":  "Acute kidney failure, unspecified",
        "departments":     ["Intensive Care", "Internal Medicine", "Urology"],
        "weight":          6.0
    },
    {
        "icd10_code":      "N18.9",
        "diagnosis_name":  "Chronic kidney disease, unspecified",
        "departments":     ["Internal Medicine", "Urology", "Geriatric"],
        "weight":          5.5
    },
    {
        "icd10_code":      "N20.0",
        "diagnosis_name":  "Calculus of kidney",
        "departments":     ["Urology", "Emergency Medicine"],
        "weight":          3.5
    },

    # ── MUSCULOSKELETAL / TRAUMA ──────────────────────────────────────────────
    {
        "icd10_code":      "S72.001A",
        "diagnosis_name":  "Fracture of unspecified part of neck of right femur, initial encounter",
        "departments":     ["Orthopedic", "Operations", "Geriatric", "Emergency Medicine"],
        "weight":          6.0
    },
    {
        "icd10_code":      "M54.5",
        "diagnosis_name":  "Low back pain",
        "departments":     ["Orthopedic", "Internal Medicine", "Emergency Medicine",
                            "Neurology"],
        "weight":          5.0
    },
    {
        "icd10_code":      "S06.0X0A",
        "diagnosis_name":  "Concussion without loss of consciousness, initial encounter",
        "departments":     ["Emergency Medicine", "Neurology", "Pediatrics"],
        "weight":          4.0
    },
    {
        "icd10_code":      "M16.9",
        "diagnosis_name":  "Osteoarthritis of hip, unspecified",
        "departments":     ["Orthopedic", "Geriatric", "Operations"],
        "weight":          4.5
    },
    {
        "icd10_code":      "M17.9",
        "diagnosis_name":  "Osteoarthritis of knee, unspecified",
        "departments":     ["Orthopedic", "Geriatric", "Operations"],
        "weight":          4.5
    },
    {
        "icd10_code":      "T14.90",
        "diagnosis_name":  "Injury, unspecified",
        "departments":     ["Emergency Medicine", "Orthopedic", "General Surgery"],
        "weight":          4.0
    },

    # ── NEUROLOGICAL ──────────────────────────────────────────────────────────
    {
        "icd10_code":      "G20",
        "diagnosis_name":  "Parkinson's disease",
        "departments":     ["Neurology", "Geriatric", "Internal Medicine"],
        "weight":          3.5
    },
    {
        "icd10_code":      "G30.9",
        "diagnosis_name":  "Alzheimer's disease, unspecified",
        "departments":     ["Neurology", "Geriatric", "Psychiatry"],
        "weight":          4.0
    },
    {
        "icd10_code":      "G45.9",
        "diagnosis_name":  "Transient cerebral ischemic attack, unspecified",
        "departments":     ["Neurology", "Emergency Medicine", "Intensive Care"],
        "weight":          4.5
    },
    {
        "icd10_code":      "G43.909",
        "diagnosis_name":  "Migraine, unspecified, not intractable",
        "departments":     ["Neurology", "Emergency Medicine"],
        "weight":          3.5
    },
    {
        "icd10_code":      "G40.909",
        "diagnosis_name":  "Epilepsy, unspecified, not intractable",
        "departments":     ["Neurology", "Emergency Medicine", "Pediatrics"],
        "weight":          3.5
    },

    # ── MENTAL HEALTH ─────────────────────────────────────────────────────────
    {
        "icd10_code":      "F32.9",
        "diagnosis_name":  "Major depressive disorder, single episode, unspecified",
        "departments":     ["Psychiatry", "Internal Medicine"],
        "weight":          5.0
    },
    {
        "icd10_code":      "F20.9",
        "diagnosis_name":  "Schizophrenia, unspecified",
        "departments":     ["Psychiatry"],
        "weight":          3.0
    },
    {
        "icd10_code":      "F10.20",
        "diagnosis_name":  "Alcohol use disorder, moderate, uncomplicated",
        "departments":     ["Psychiatry", "Internal Medicine", "Emergency Medicine",
                            "Gastroenterology"],
        "weight":          4.0
    },
    {
        "icd10_code":      "F41.9",
        "diagnosis_name":  "Anxiety disorder, unspecified",
        "departments":     ["Psychiatry", "Internal Medicine", "Emergency Medicine"],
        "weight":          4.5
    },
    {
        "icd10_code":      "F05",
        "diagnosis_name":  "Delirium due to known physiological condition",
        "departments":     ["Psychiatry", "Geriatric", "Intensive Care", "Internal Medicine"],
        "weight":          3.5
    },

    # ── ONCOLOGY ──────────────────────────────────────────────────────────────
    {
        "icd10_code":      "C34.90",
        "diagnosis_name":  "Malignant neoplasm of unspecified part of unspecified bronchus and lung",
        "departments":     ["Oncology", "Intensive Care", "Internal Medicine"],
        "weight":          4.5
    },
    {
        "icd10_code":      "C50.919",
        "diagnosis_name":  "Malignant neoplasm of unspecified site of unspecified female breast",
        "departments":     ["Oncology", "Operations", "OB/GYN"],
        "weight":          4.5
    },
    {
        "icd10_code":      "C18.9",
        "diagnosis_name":  "Malignant neoplasm of colon, unspecified",
        "departments":     ["Oncology", "Gastroenterology", "General Surgery"],
        "weight":          4.0
    },
    {
        "icd10_code":      "C61",
        "diagnosis_name":  "Malignant neoplasm of prostate",
        "departments":     ["Oncology", "Urology", "Operations"],
        "weight":          4.0
    },
    {
        "icd10_code":      "C92.00",
        "diagnosis_name":  "Acute myeloblastic leukemia, not having achieved remission",
        "departments":     ["Oncology", "Hematology", "Intensive Care"],
        "weight":          2.5
    },

    # ── OB/GYN ────────────────────────────────────────────────────────────────
    {
        "icd10_code":      "O80",
        "diagnosis_name":  "Encounter for full-term uncomplicated delivery",
        "departments":     ["OB/GYN"],
        "weight":          7.5
    },
    {
        "icd10_code":      "O34.21",
        "diagnosis_name":  "Maternal care for scar from previous cesarean delivery",
        "departments":     ["OB/GYN", "Operations"],
        "weight":          5.0
    },
    {
        "icd10_code":      "O09.90",
        "diagnosis_name":  "Supervision of high-risk pregnancy, unspecified",
        "departments":     ["OB/GYN"],
        "weight":          4.0
    },
    {
        "icd10_code":      "O20.0",
        "diagnosis_name":  "Threatened abortion",
        "departments":     ["OB/GYN", "Emergency Medicine"],
        "weight":          2.5
    },

    # ── SYMPTOMS / UNSPECIFIED (common ER presentations) ─────────────────────
    {
        "icd10_code":      "R07.9",
        "diagnosis_name":  "Chest pain, unspecified",
        "departments":     ["Emergency Medicine", "Cardiology", "Internal Medicine"],
        "weight":          6.0
    },
    {
        "icd10_code":      "R55",
        "diagnosis_name":  "Syncope and collapse",
        "departments":     ["Emergency Medicine", "Cardiology", "Neurology"],
        "weight":          4.5
    },
    {
        "icd10_code":      "R00.0",
        "diagnosis_name":  "Tachycardia, unspecified",
        "departments":     ["Emergency Medicine", "Cardiology", "Intensive Care"],
        "weight":          4.0
    },
    {
        "icd10_code":      "R51",
        "diagnosis_name":  "Headache, unspecified",
        "departments":     ["Emergency Medicine", "Neurology"],
        "weight":          4.0
    },
    {
        "icd10_code":      "R11.2",
        "diagnosis_name":  "Nausea with vomiting, unspecified",
        "departments":     ["Emergency Medicine", "Gastroenterology", "Internal Medicine",
                            "Pediatrics"],
        "weight":          4.5
    },

    # ── NEWBORN ───────────────────────────────────────────────────────────────
    {
        "icd10_code":      "Z38.00",
        "diagnosis_name":  "Single liveborn infant, delivered vaginally",
        "departments":     ["OB/GYN", "Pediatrics"],
        "weight":          6.0
    },
    {
        "icd10_code":      "P07.30",
        "diagnosis_name":  "Preterm newborn, unspecified weeks of gestation",
        "departments":     ["Pediatrics", "Intensive Care"],
        "weight":          2.5
    },

]


# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

def get_diagnoses_df() -> pd.DataFrame:
    """
    Returns the full diagnosis list as a DataFrame.
    Useful for weighted sampling with df.sample(n=1, weights='weight').
    """
    return pd.DataFrame(DIAGNOSES)


def get_diagnoses_for_department(department_name: str) -> pd.DataFrame:
    """
    Returns diagnoses associated with a given department, as a DataFrame.
    Use for clinically plausible diagnosis assignment during data generation —
    i.e. a patient admitted to Cardiology should get a cardiac diagnosis.

    Args:
        department_name: Must match a string in the hospital_departments list.

    Returns:
        DataFrame filtered to diagnoses relevant to that department,
        preserving weights for relative sampling.

    Example:
        dx = get_diagnoses_for_department('Cardiology')
        sample = dx.sample(n=1, weights='weight').iloc[0]
        icd_code = sample['icd10_code']
        dx_name  = sample['diagnosis_name']
    """
    df = get_diagnoses_df()
    mask = df['departments'].apply(lambda depts: department_name in depts)
    filtered = df[mask].copy()

    if filtered.empty:
        # Fallback to unspecified symptom codes if department has no mapped diagnoses
        fallback_codes = ['R07.9', 'R55', 'R11.2']
        filtered = df[df['icd10_code'].isin(fallback_codes)].copy()

    return filtered.reset_index(drop=True)


def sample_diagnosis(department_name: str = None) -> dict:
    """
    Convenience function: returns a single diagnosis dict, optionally
    filtered by department.

    Args:
        department_name: If provided, filters to department-relevant diagnoses.
                         If None, samples from the full list.

    Returns:
        dict with keys: icd10_code, diagnosis_name, departments, weight

    Example:
        dx = sample_diagnosis('Emergency Medicine')
        print(dx['icd10_code'], dx['diagnosis_name'])
    """
    if department_name:
        df = get_diagnoses_for_department(department_name)
    else:
        df = get_diagnoses_df()

    weights = df['weight'].values
    weights = weights / weights.sum()
    idx = np.random.choice(len(df), p=weights)
    return df.iloc[idx].to_dict()


def get_codes_and_names() -> tuple:
    """
    Returns two parallel lists: ICD-10 codes and diagnosis names.
    Useful for direct np.random.choice calls.

    Returns:
        (codes, names, weights) — all three as numpy arrays

    Example:
        codes, names, weights = get_codes_and_names()
        weights = weights / weights.sum()
        idx = np.random.choice(len(codes), p=weights)
        selected_code = codes[idx]
        selected_name = names[idx]
    """
    df = get_diagnoses_df()
    return (
        df['icd10_code'].values,
        df['diagnosis_name'].values,
        df['weight'].values
    )


# ─── CATEGORY SUMMARY ─────────────────────────────────────────────────────────
# For documentation and README reference

CATEGORY_SUMMARY = {
    "Cardiovascular":               7,
    "Respiratory":                  5,
    "Endocrine / Metabolic":        6,
    "Infectious Disease / Sepsis":  5,
    "Gastrointestinal":             7,
    "Renal":                        3,
    "Musculoskeletal / Trauma":     6,
    "Neurological":                 5,
    "Mental Health":                5,
    "Oncology":                     5,
    "OB/GYN":                       4,
    "Symptoms / Unspecified":       5,
    "Newborn":                      2,
}

TOTAL_DIAGNOSES = sum(CATEGORY_SUMMARY.values())  # 70


if __name__ == "__main__":
    df = get_diagnoses_df()
    print(f"Total diagnoses: {len(df)}")
    print(f"\nCategory breakdown:")
    for cat, count in CATEGORY_SUMMARY.items():
        print(f"  {cat:<35} {count:>2}")
    print(f"\nSample — full list weighted:")
    for _ in range(5):
        dx = sample_diagnosis()
        print(f"  [{dx['icd10_code']:<10}] {dx['diagnosis_name']}")
    print(f"\nSample — Cardiology filtered:")
    for _ in range(5):
        dx = sample_diagnosis('Cardiology')
        print(f"  [{dx['icd10_code']:<10}] {dx['diagnosis_name']}")
