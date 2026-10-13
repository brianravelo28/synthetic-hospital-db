"""
Diagnosis-to-treatment mapping for the generator.

Before this module, procedures, medications and tests were drawn uniformly at
random from their catalogs, so a cardiac-surgery bypass could land on a
toddler's admission and chemotherapy on a patient with no cancer diagnosis
(measured: 4,699 contradictions across six checks at large scale; see
docs/METHODOLOGY.md).

Now each admission's diagnoses decide which treatments are plausible:

    ICD-10 code -> family -> procedure ids / drug names / test names

with a code-level override where one code is far more specific than its family
(appendicitis -> appendectomy, type 1 diabetes -> insulin only), a share of
"general" care (acetaminophen, a metabolic panel, a ward round) that can
happen on any admission, and demographic eligibility filters (deliveries need
a female patient of childbearing age; joint replacement needs an adult).

This is generator-side only. The validator's Group 8 is written separately,
from CPT codes and drug names, so it checks the output instead of echoing this
file. The mapping is deliberately coarse: it is plausible, not clinical advice.
"""

import random

# Share of treatments drawn from the general pool even when a diagnosis match exists
GENERAL_SHARE = 0.20

# Delivery procedures need a female patient of childbearing age (ages at admission)
DELIVERY_PROCEDURES = ("PRC-021", "PRC-022")
DELIVERY_AGE_RANGE  = (15, 50)
# Major adult surgery
ADULT_ONLY_PROCEDURES = ("PRC-008", "PRC-018", "PRC-019", "PRC-020", "PRC-023")
ADULT_AGE = 18
PAP_SMEAR_MIN_AGE = 21

# Drugs not given to young children in this catalog (anticoagulant, statin, opioid, ...)
NOT_FOR_YOUNG_CHILDREN = ("Warfarin", "Digoxin", "Amiodarone", "Atorvastatin", "Lisinopril",
                          "Metoprolol", "Hydrocodone", "Ketorolac", "Haloperidol",
                          "Sertraline", "Metformin", "Morphine")
YOUNG_CHILD_AGE = 12


# ── code -> family ────────────────────────────────────────────────────────

def family_of(icd10_code: str) -> str:
    c = icd10_code
    if c in ("Z38.00", "P07.30"):                    return "newborn"
    if c in ("I63.9", "G45.9") or c[0] == "G":       return "neuro"
    if c in ("R51", "S06.0X0A"):                     return "neuro"
    if c in ("R07.9", "R00.0", "R55"):               return "cardiac"
    if c == "R11.2":                                 return "gi"
    if c[0] == "I":                                  return "cardiac"
    if c[0] == "J":                                  return "respiratory"
    if c[:3] in ("E10", "E11"):                      return "diabetes"
    if c[0] == "E":                                  return "metabolic"
    if c[0] in ("A", "B") or c == "N39.0":           return "infection"
    if c[0] == "K":                                  return "gi"
    if c[0] == "N":                                  return "renal"
    if c[0] in ("S", "M", "T"):                      return "ortho"
    if c[0] == "F":                                  return "psych"
    if c[0] == "C":                                  return "oncology"
    if c[0] == "O":                                  return "obstetric"
    return "general"


# ── family pools (ids / names exactly as in hospital_generator's catalogs) ──

FAMILY_PROCEDURES = {
    "cardiac":     ["PRC-005", "PRC-006", "PRC-007", "PRC-008", "PRC-015", "PRC-012"],
    "neuro":       ["PRC-014", "PRC-016", "PRC-017"],
    "respiratory": ["PRC-012", "PRC-004", "PRC-002"],
    "diabetes":    ["PRC-012", "PRC-029"],
    "metabolic":   ["PRC-012", "PRC-029"],
    "infection":   ["PRC-003", "PRC-013", "PRC-012"],
    "gi":          ["PRC-013", "PRC-023", "PRC-024"],
    "renal":       ["PRC-013", "PRC-027"],
    "ortho":       ["PRC-012"],
    "psych":       ["PRC-028"],
    "oncology":    ["PRC-025", "PRC-026", "PRC-013", "PRC-024"],
    "obstetric":   ["PRC-021", "PRC-022"],
    "newborn":     ["PRC-029"],
    "general":     ["PRC-029", "PRC-012", "PRC-013"],      # ward round, chest film, CT
}
FAMILY_MEDICATIONS = {
    "cardiac":     ["Metoprolol", "Lisinopril", "Atorvastatin", "Warfarin", "Heparin", "Furosemide", "Digoxin", "Amiodarone"],
    "neuro":       ["Levetiracetam", "Lorazepam", "Atorvastatin", "Heparin", "Dexamethasone", "Acetaminophen"],
    "respiratory": ["Albuterol", "Ipratropium", "Prednisone", "Azithromycin", "Ceftriaxone", "Dexamethasone"],
    "diabetes":    ["Metformin", "Insulin Glargine", "Insulin Regular"],
    "metabolic":   ["Furosemide", "Omeprazole"],
    "infection":   ["Vancomycin", "Ceftriaxone", "Piperacillin-Tazobactam", "Ciprofloxacin", "Amoxicillin", "Azithromycin"],
    "gi":          ["Omeprazole", "Ondansetron", "Metoclopramide", "Ciprofloxacin"],
    "renal":       ["Furosemide", "Ciprofloxacin", "Ketorolac", "Ondansetron"],
    "ortho":       ["Morphine", "Hydrocodone", "Ibuprofen", "Ketorolac", "Acetaminophen", "Heparin"],
    "psych":       ["Sertraline", "Haloperidol", "Lorazepam"],
    "oncology":    ["Ondansetron", "Dexamethasone", "Morphine", "Acetaminophen"],
    "obstetric":   ["Acetaminophen", "Ibuprofen", "Ondansetron"],
    "newborn":     ["Acetaminophen", "Amoxicillin"],
    "general":     ["Acetaminophen", "Ondansetron", "Omeprazole"],
}
FAMILY_TESTS = {
    "cardiac":     ["12-Lead EKG", "Echocardiogram", "Stress Test", "Holter Monitor", "Lipid Panel", "Coagulation Panel"],
    "neuro":       ["MRI Brain", "EEG", "Nerve Conduction Study", "Lumbar Puncture"],
    "respiratory": ["Chest X-Ray", "Sputum Culture", "Blood Culture", "Complete Blood Count"],
    "diabetes":    ["Basic Metabolic Panel", "Comprehensive Metabolic Panel", "Urinalysis with Microscopy"],
    "metabolic":   ["Basic Metabolic Panel", "Comprehensive Metabolic Panel", "Thyroid Panel"],
    "infection":   ["Blood Culture", "Urine Culture", "Wound Culture", "Complete Blood Count"],
    "gi":          ["CT Abdomen", "Ultrasound Abdomen", "Comprehensive Metabolic Panel", "Complete Blood Count", "Tissue Biopsy"],
    "renal":       ["Basic Metabolic Panel", "Urinalysis with Microscopy", "Urine Culture", "Ultrasound Abdomen", "CT Abdomen"],
    "ortho":       ["Complete Blood Count", "Coagulation Panel", "Chest X-Ray"],
    "psych":       ["Comprehensive Metabolic Panel", "Thyroid Panel"],
    "oncology":    ["Tissue Biopsy", "Bone Marrow Biopsy", "CT Abdomen", "Complete Blood Count"],
    "obstetric":   ["Ultrasound Abdomen", "Complete Blood Count", "Urinalysis with Microscopy", "Pap Smear"],
    "newborn":     ["Complete Blood Count", "Blood Culture"],
    "general":     ["Complete Blood Count", "Basic Metabolic Panel", "Urinalysis with Microscopy"],
}

# Where one code is more specific than its family
CODE_PROCEDURES = {
    "K35.80": ["PRC-009"],                  # appendicitis -> appendectomy
    "K80.20": ["PRC-010"],                  # gallstones -> cholecystectomy
    "K56.60": ["PRC-011", "PRC-013"],       # bowel obstruction -> hernia repair / CT
    "N20.0":  ["PRC-027"],                  # kidney stone -> ureteral stone removal
    "S72.001A": ["PRC-020"],                # hip fracture -> fixation
    "M16.9":  ["PRC-018"],                  # hip osteoarthritis -> hip replacement
    "M17.9":  ["PRC-019"],                  # knee osteoarthritis -> knee replacement
    "O80":    ["PRC-021"],                  # normal delivery -> vaginal delivery
    "O34.21": ["PRC-022"],                  # uterine scar -> cesarean
    "I21.9":  ["PRC-006", "PRC-005"],       # myocardial infarction -> angiography / echo
    "I48.91": ["PRC-007", "PRC-005"],       # atrial fibrillation -> cardioversion / echo
    "J96.00": ["PRC-004", "PRC-002"],       # respiratory failure -> ventilation / intubation
    "O09.90": [],                           # supervised pregnancy: no delivery procedure
    "O20.0":  [],                           # threatened abortion: no delivery procedure
}
CODE_MEDICATIONS = {
    "E10.9": ["Insulin Glargine", "Insulin Regular"],       # type 1: insulin only
    "G40.909": ["Levetiracetam", "Lorazepam"],
    "I48.91": ["Warfarin", "Metoprolol", "Amiodarone", "Digoxin"],
    "K35.80": ["Ceftriaxone", "Ondansetron", "Morphine"],
}


# ── selection ─────────────────────────────────────────────────────────────

def _unique(seq):
    return list(dict.fromkeys(seq))                         # stable, hash-seed independent


def _eligible_procedure(proc_id: str, gender: str, age: int) -> bool:
    if proc_id in DELIVERY_PROCEDURES:
        return gender == "F" and DELIVERY_AGE_RANGE[0] <= age <= DELIVERY_AGE_RANGE[1]
    if proc_id in ADULT_ONLY_PROCEDURES:
        return age >= ADULT_AGE
    return True


def _eligible_medication(drug: str, gender: str, age: int) -> bool:
    return not (age < YOUNG_CHILD_AGE and drug in NOT_FOR_YOUNG_CHILDREN)


def _eligible_test(test: str, gender: str, age: int) -> bool:
    if test == "Pap Smear":
        return gender == "F" and age >= PAP_SMEAR_MIN_AGE
    return True


def _pool(kind: str, dx_codes, code_map, family_map, eligible, gender, age):
    pool = []
    for code in dx_codes:
        pool.extend(code_map[code] if code in code_map else family_map.get(family_of(code), []))
    return [x for x in _unique(pool) if eligible(x, gender, age)]


def _pick(kind, dx_codes, code_map, family_map, eligible, gender, age, everything):
    pool = _pool(kind, dx_codes, code_map, family_map, eligible, gender, age)
    if not pool or random.random() < GENERAL_SHARE:
        pool = [x for x in family_map["general"] if eligible(x, gender, age)]
    if not pool:                                             # nothing eligible: any eligible catalog item
        pool = [x for x in everything if eligible(x, gender, age)]
    return random.choice(pool)


def pick_procedure(dx_codes, gender, age, all_procedure_ids, emergency=False) -> str:
    """One procedure id suited to the admission's diagnoses and the patient."""
    if emergency and random.random() < 0.10 and _eligible_procedure("PRC-001", gender, age):
        return "PRC-001"                                      # emergency department visit
    return _pick("procedure", dx_codes, CODE_PROCEDURES, FAMILY_PROCEDURES,
                 _eligible_procedure, gender, age, all_procedure_ids)


def pick_medication(dx_codes, gender, age, all_drug_names) -> str:
    return _pick("medication", dx_codes, CODE_MEDICATIONS, FAMILY_MEDICATIONS,
                 _eligible_medication, gender, age, all_drug_names)


def pick_test(dx_codes, gender, age, all_test_names) -> str:
    return _pick("test", dx_codes, {}, FAMILY_TESTS,
                 _eligible_test, gender, age, all_test_names)
