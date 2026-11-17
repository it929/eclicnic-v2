"""
Drug / medical item categories for the Central Medical Store and pharmacies.

`infer_product_category(name, uom)` gives a best-guess category for items that
were created without one (bulk imports, GRN quick-adds, legacy records).
Staff can always override the category from the Edit Medication modal.
"""
import re

PRODUCT_CATEGORIES = [
    ("vaccine", "Vaccines"),
    ("tablet", "Tablets"),
    ("capsule", "Capsules"),
    ("injection", "Injections"),
    ("infusion", "IV Fluids & Infusions"),
    ("syrup", "Syrups & Suspensions"),
    ("cream", "Creams & Ointments"),
    ("drops", "Eye / Ear / Nasal Drops"),
    ("inhaler", "Inhalers & Nebules"),
    ("suppository", "Suppositories & Pessaries"),
    ("sachet", "Sachets & Powders"),
    ("antiseptic", "Antiseptics & Disinfectants"),
    ("consumable", "Medical Consumables"),
    ("lab", "Lab Reagents & Test Kits"),
    ("other", "Others"),
]

VALID_CATEGORIES = {code for code, _ in PRODUCT_CATEGORIES}
CATEGORY_LABELS = dict(PRODUCT_CATEGORIES)

# Order matters: the first matching rule wins. Name rules are checked before
# the unit of measure because many legacy items carry a default "tablets" UoM.
# Many imported names are run together ("INJ1MG", "CAP500MG"), so most rules
# anchor on the start of a word only.
_NAME_RULES = [
    ("vaccine", r"vaccin|\bbcg\b|\b[bt]?opv\b|\bipv\b|pentaval|pentavac|\bpcv\s?\d*\b|rotavirus|rotarix|rotateq|rotasil|"
                r"measles|\bmmr|yellow fever|\bhpv\b|tetanus toxoid|t\.?\s?toxoi?d|toxiod|\btt\b|\btd\b|menafri|"
                r"meningococcal|menactra|menveo|anti-?\s?rabies|rabies vac|varicella|\bhib\b|engerix|euvax|genevac|"
                r"hep(atitis)?\s?b\s?(vacc|0\b|birth|adult|child|paed)|cholera vac|shanc?hol|shancol|typhoid (vac|fever)|"
                r"typhim|covid.?19|covishield|comirnaty|avaxim|cervarix|gardasil|hexaxim|infanrix|pentaxim|"
                r"p[ri]{1,2}orix|prevenar|s[yn]{1,2}florix|twinrix|adacel|boostrix|vaxigrip|flu vac"),
    ("lab", r"\b(test|testing|diagnostic|rapid|malaria|hiv|hbsag|hcv|pregnancy|glucose|urine|widal|vdrl)\s?"
            r"(test\s?)?(kits?|strips?|cassettes?|devices?)|reagent|\bm?rdts?\b|culture media|microscope slide|"
            r"urinalysis|\bedta\b|blood bag|specimen|sample bottle"),
    ("antiseptic", r"savlon|dettol|povidon|providon|\biodine|hydrogen peroxide|chlorhexidine|hexedene|"
                   r"methylated spirit|\bspirit\b|\bjik\b|hypochlorite|potassium permanganate|\bizal\b|"
                   r"hand sanitizer|mouth\s?wash|disinfectant|antiseptic"),
    ("consumable", r"needle|\bsyringes?\b(?!.*\b(mg|mcg|iu)\b)|cannul|canul|catheter|gloves?\b|gauze|bandage|plaster|"
                   r"cotton|\bwool\b|giving set|infusion set|\bblades?\b|suture|urine bag|\bmasks?\b|\bmas$|\bswabs?\b|"
                   r"strapping|crepe|elastoplast|diaper|nappy|sanitary pad|scalp vein|lancet|condom|apron|"
                   r"tongue depressor|feeding\s+tube|\bng\s?tube|\bngt\b|cord clamp|face shield|\bdrapes?\b|\bgowns?\b|"
                   r"\bcontainer\b|sharps|plastic bag|electrodes?\b|oxygen|re-?breath|bp cuff|thermometer|tourniquet|"
                   r"\bsupport\b|stocking|crutch|collar|\bsling\b|brace\b|corset|coset|walking frame|wheel\s?chair|"
                   r"\bnylon|vicryl|surgicryl|chromic|prolene|catgut|\bmesh\b|stap+ler|scotch\s?cast|plaster of paris|"
                   r"softban|sofratul|surgicel|haemostat|esu pencil|silver nitrate|copper\s?-?\s?t\b|\biucd|soluset|"
                   r"colostomy|stoma bag|\bkit\b"),
    ("drops", r"\bdrops?|eye drop|ear drop|nasal|\bgtt\b|opthalmic|ophthalmic|\botic\b|\btears\b"),
    ("suppository", r"suppos|pessar|\bsupp\b|\bpess\b|rectal|vaginal tab"),
    ("infusion", r"dextrose|saline|ringer|darrow|\binfusion\b|\binf\b|\bivf?\b(?!.*\b(inj|amp)\b)|haemac+el|heamac+el|"
                 r"gelofusine|mannitol|sodium chloride\s?0|\bd/s\b|\bn/s\b|plasma expander|isoplasma|hartmann|"
                 r"combilipid|intralipid|kabiven|aminoven|\btpn\b|sterile water|\bdrip\b|\bfluid\b"),
    ("injection", r"\binj|injection|\bvials?\b|ampoule|\bamps?\b|\bim/iv\b|prefilled|pre-filled|depot|\bdepo\b|"
                  r"insulin|insuman|propofol|atracurium|suxameth|ketamine|adrenalin|ergometrine|oxytocin|syntocinon|"
                  r"testosterone|sayana|leuprolide|lupron|iron sucrose|immunoglobulin|rhogam|heparin|clexane|"
                  r"enoxaparin|vasopressin|vasoprin|\bpen\b"),
    ("inhaler", r"inhaler|nebul|\bpuffs?\b|rotacap|\bmdi\b|turbohaler|accuhaler|evohaler|pulmicort|ipratr?opium|respule"),
    ("cream", r"cream|crem\b|ointment|onitment|\boint\b|(?<!soft )\bgel\b|lotion|\bpaste\b|\bbalm\b|\bcrm\b|emollient|"
              r"liniment|\bspray|jelly|shampoo|bonjela|benzyl benzoate|podophyll"),
    ("syrup", r"syrup|\bsyr(?!inge)|\bsusp|\bsus\b|suspension|elixir|\bliquid\b|mixture|linctus|oral sol|solution|"
              r"\bdrink\b|tonic|\bmist\b|expectorant|cough|\boil\b|/\s?bottle|\bbottle|(?<![/\d])\d+\s?mls?\b|\bmls?\b"),
    ("sachet", r"sachet|powder|\bors\b|granule|\bpwd\b"),
    ("capsule", r"\bcaps?(?![a-z])|capsule|soft\s?gel"),
    ("tablet", r"\btabs?(?![a-z])|tablet|caplet|chewable|dispers|\bdt\b|lozenge|effervescent|strepsils"),
]
_COMPILED_RULES = [(code, re.compile(pattern, re.IGNORECASE)) for code, pattern in _NAME_RULES]

_UOM_FALLBACK = {
    "tablets": "tablet",
    "capsules": "capsule",
    "ampoules": "injection",
    "vial": "injection",
    "prefilled_syringe": "injection",
    "bottles": "syrup",
    "mls": "syrup",
    "tubes": "cream",
    "drops": "drops",
    "puffs": "inhaler",
    "suppository": "suppository",
    "pessary": "suppository",
    "sachets": "sachet",
    "syringes": "consumable",
    "rolls": "consumable",
    "pieces": "consumable",
}


def normalize_category(value):
    """Return a valid category code for user input (code or label), or '' if unknown."""
    if value is None:
        return ''
    raw = str(value).strip().lower()
    if not raw:
        return ''
    if raw in VALID_CATEGORIES:
        return raw
    for code, label in PRODUCT_CATEGORIES:
        if raw == label.lower():
            return code
    # Accept simple plurals / common aliases ("tablets", "injections", "vaccines", ...)
    aliases = {
        'tablets': 'tablet', 'capsules': 'capsule', 'injections': 'injection', 'vaccines': 'vaccine',
        'infusions': 'infusion', 'iv fluids': 'infusion', 'fluids': 'infusion', 'syrups': 'syrup',
        'suspension': 'syrup', 'suspensions': 'syrup', 'creams': 'cream', 'ointment': 'cream',
        'ointments': 'cream', 'drop': 'drops', 'inhalers': 'inhaler', 'suppositories': 'suppository',
        'pessary': 'suppository', 'pessaries': 'suppository', 'sachets': 'sachet', 'consumables': 'consumable',
        'reagent': 'lab', 'reagents': 'lab', 'antiseptics': 'antiseptic', 'disinfectant': 'antiseptic',
        'disinfectants': 'antiseptic', 'others': 'other',
    }
    return aliases.get(raw, '')


def infer_product_category(name, uom=None):
    """Best-guess category from the item name, falling back to its unit of measure."""
    text = str(name or '')
    for code, rx in _COMPILED_RULES:
        if rx.search(text):
            return code
    return _UOM_FALLBACK.get(str(uom or '').strip().lower(), 'other')


# ---------------------------------------------------------------------------
# Dosage type / unit of measure (Product.minimum_UoM)
# ---------------------------------------------------------------------------
_CATEGORY_UOM = {
    "tablet": "tablets",
    "capsule": "capsules",
    "vaccine": "vial",
    "injection": "ampoules",
    "infusion": "bottles",
    "syrup": "bottles",
    "cream": "tubes",
    "drops": "drops",
    "inhaler": "puffs",
    "suppository": "suppository",
    "sachet": "sachets",
    "antiseptic": "bottles",
    "consumable": "pieces",
    "lab": "packs",
    "other": "others",
}

_RX = lambda p: re.compile(p, re.IGNORECASE)  # noqa: E731
_PREFILLED = _RX(r"prefilled|pre-filled|\bpen\b|syringe")
_VIAL = _RX(r"\bvials?\b|insulin|insuman|powder|\bpwd\b|\d+(\.\d+)?\s?g\b|\bmu\b|immunoglobulin|rhogam")
_ORAL_VACCINE = _RX(r"\bb?opv\b|oral polio|rota(virus|rix|teq|sil)|cholera|shan?c?hol")
_BOTTLE_TOPICAL = _RX(r"lotion|shampoo|spray|liniment|emulsion")
_NEBULE = _RX(r"nebul|respule")
_PESSARY = _RX(r"pessar|\bpess\b|vaginal")
_ROLLS = _RX(r"plaster|strapping|crepe|bandage|cotton|\bwool\b|gauze|elastoplast|scotch\s?cast")


def infer_dosage_uom(category, name=''):
    """Best-guess dosage type / UoM for a product from its category and name."""
    text = str(name or '')
    cat = normalize_category(category) or infer_product_category(text)
    if cat == "vaccine":
        if _ORAL_VACCINE.search(text):
            return "drops"
        return "prefilled_syringe" if _PREFILLED.search(text) else "vial"
    if cat == "injection":
        if _PREFILLED.search(text):
            return "prefilled_syringe"
        return "vial" if _VIAL.search(text) else "ampoules"
    if cat == "cream" and _BOTTLE_TOPICAL.search(text):
        return "bottles"
    if cat == "inhaler" and _NEBULE.search(text):
        return "ampoules"
    if cat == "suppository" and _PESSARY.search(text):
        return "pessary"
    if cat == "consumable" and _ROLLS.search(text):
        return "rolls"
    return _CATEGORY_UOM.get(cat, "others")
