"""Local pseudonymization policy over reviewed findings."""

CATEGORY_GROUPS = {
    "Identity and contact": ("PER", "DOB", "ID_PER", "ID_MISC", "NUM_PHONE", "EMAIL", "LOC", "NUM_CAR"),
    "Organizations and finance": ("ORG", "COMPANY_ID", "PVM", "IBAN", "VALUE"),
    "Personal context": ("AGE", "DATE", "DURATION", "TIME", "OCC", "EDU", "FAM",
                         "GENDER", "MAR", "NAT", "HEALTH", "ETH", "REL", "SEX", "POL"),
    "Other": ("MISC", "MANUAL"),
}
ALL_CATEGORIES = frozenset(category for group in CATEGORY_GROUPS.values() for category in group)
PROFILES = {
    "Standard": ALL_CATEGORIES - {"DATE", "TIME", "DURATION", "VALUE"},
    "Strict": ALL_CATEGORIES,
    "Identity only": frozenset(CATEGORY_GROUPS["Identity and contact"]),
}


def selected_indices(spans, categories, excluded):
    return [index for index, span in enumerate(spans)
            if (span.label in categories or span.source == "ocr-human-verified") and span not in excluded]
