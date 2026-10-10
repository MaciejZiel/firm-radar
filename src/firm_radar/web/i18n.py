"""Polish (default) and English UI strings."""

from __future__ import annotations

from typing import Literal

Lang = Literal["pl", "en"]
LANGS: tuple[Lang, ...] = ("pl", "en")

TEXTS: dict[str, dict[Lang, str]] = {
    "tagline": {
        "pl": "Profil firmy z oficjalnych rejestrów publicznych – z historią zmian.",
        "en": "Company profiles from official public registries – with change history.",
    },
    "nav.search": {"pl": "Szukaj", "en": "Search"},
    "nav.sources": {"pl": "Źródła danych", "en": "Data sources"},
    "nav.api": {"pl": "API", "en": "API"},
    "search.label": {"pl": "KRS, NIP, REGON lub nazwa", "en": "KRS, NIP, REGON or name"},
    "search.placeholder": {
        "pl": "np. 0000019193 albo 5250000251",
        "en": "e.g. 0000019193 or 5250000251",
    },
    "search.button": {"pl": "Sprawdź", "en": "Look up"},
    "search.hint": {
        "pl": "Numery sprawdzamy bezpośrednio w KRS i na białej liście VAT. Po nazwie "
        "przeszukujemy firmy już sprawdzone w tym serwisie i wykonawców z BZP.",
        "en": "Numbers are checked live in KRS and the VAT white list. Names are matched "
        "against companies already looked up here and against BZP contractors.",
    },
    "search.examples": {"pl": "Przykłady", "en": "Examples"},
    "search.none": {"pl": "Nic nie znaleziono.", "en": "Nothing found."},
    "search.candidates": {
        "pl": "Wykonawcy z ogłoszeń BZP (kliknij, aby pobrać profil po NIP)",
        "en": "Contractors from BZP notices (click to fetch the profile by NIP)",
    },
    "search.awards": {"pl": "udzielonych zamówień", "en": "contract awards"},
    "search.error": {"pl": "Nie udało się wyszukać", "en": "Search failed"},
    "recent.title": {"pl": "Ostatnio sprawdzane", "en": "Recently checked"},
    "recent.empty": {
        "pl": "Jeszcze nic – wpisz numer KRS lub NIP powyżej.",
        "en": "Nothing yet – enter a KRS or NIP number above.",
    },
    "company.identifiers": {"pl": "Identyfikatory", "en": "Identifiers"},
    "company.legal_form": {"pl": "Forma prawna", "en": "Legal form"},
    "company.address": {"pl": "Siedziba i adres", "en": "Registered address"},
    "company.website": {"pl": "Strona WWW", "en": "Website"},
    "company.capital": {"pl": "Kapitał zakładowy", "en": "Share capital"},
    "company.registered_on": {"pl": "Wpis do KRS", "en": "Registered in KRS"},
    "company.last_entry": {"pl": "Ostatni wpis", "en": "Latest entry"},
    "company.deregistered": {"pl": "Wykreślona z KRS", "en": "Removed from KRS"},
    "company.vat": {"pl": "Status VAT", "en": "VAT status"},
    "company.vat.active": {"pl": "Czynny podatnik VAT", "en": "Active VAT payer"},
    "company.vat.exempt": {"pl": "Zwolniony z VAT", "en": "VAT exempt"},
    "company.vat.removed": {"pl": "Wykreślony z rejestru VAT", "en": "Removed from VAT register"},
    "company.vat.none": {"pl": "Brak na białej liście", "en": "Not on the white list"},
    "company.vat.unknown": {"pl": "Nie sprawdzono", "en": "Not checked"},
    "company.accounts": {
        "pl": "Rachunki na białej liście",
        "en": "Bank accounts on the white list",
    },
    "company.accounts.count": {"pl": "liczba rachunków", "en": "accounts"},
    "company.management": {"pl": "Zarząd", "en": "Management board"},
    "company.representation": {"pl": "Sposób reprezentacji", "en": "Representation"},
    "company.supervisory": {"pl": "Organ nadzoru", "en": "Supervisory body"},
    "company.proxies": {"pl": "Prokurenci", "en": "Commercial proxies"},
    "company.masked": {
        "pl": "Dane osobowe są zanonimizowane przez Ministerstwo Sprawiedliwości w otwartym API.",
        "en": "Personal data is masked by the Ministry of Justice in the open API.",
    },
    "company.activity": {"pl": "Przeważająca działalność (PKD)", "en": "Main activity (PKD)"},
    "company.activity.other": {"pl": "pozostałe kody PKD", "en": "other PKD codes"},
    "company.refresh": {"pl": "Odśwież z rejestrów", "en": "Refresh from registries"},
    "company.refreshed": {"pl": "Sprawdzono", "en": "Checked"},
    "company.snapshot": {"pl": "Stan na", "en": "As of"},
    "company.no_krs": {
        "pl": "Podmiot nie występuje w KRS (np. jednoosobowa działalność gospodarcza).",
        "en": "Not in KRS (e.g. a sole proprietorship).",
    },
    "timeline.title": {"pl": "Historia zmian", "en": "Change history"},
    "timeline.first": {
        "pl": "Pierwszy zapis – od tej chwili śledzimy zmiany.",
        "en": "First snapshot – changes are tracked from here on.",
    },
    "timeline.nochanges": {
        "pl": "bez zmian w śledzonych polach",
        "en": "no change in tracked fields",
    },
    "timeline.compare": {"pl": "porównaj", "en": "compare"},
    "change.added": {"pl": "dodano", "en": "added"},
    "change.removed": {"pl": "usunięto", "en": "removed"},
    "change.modified": {"pl": "zmieniono", "en": "changed"},
    "procurement.title": {"pl": "Zamówienia publiczne (BZP)", "en": "Public procurement (BZP)"},
    "procurement.coverage": {
        "pl": "Przeszukane ogłoszenia o wyniku postępowania z dni",
        "en": "Contract award notices searched, published",
    },
    "procurement.none": {
        "pl": "Brak ogłoszeń o udzieleniu zamówienia tej firmie w przeszukanym okresie.",
        "en": "No contract awards to this company in the period searched.",
    },
    "procurement.nocoverage": {
        "pl": "Ogłoszenia BZP nie zostały jeszcze pobrane.",
        "en": "BZP notices have not been ingested yet.",
    },
    "procurement.awards": {"pl": "zamówień", "en": "awards"},
    "procurement.lots": {"pl": "części", "en": "lots"},
    "procurement.buyer": {"pl": "Zamawiający", "en": "Buyer"},
    "procurement.object": {"pl": "Przedmiot", "en": "Subject"},
    "procurement.date": {"pl": "Data", "en": "Date"},
    "procurement.notice": {"pl": "Ogłoszenie", "en": "Notice"},
    "sources.title": {"pl": "Źródła", "en": "Sources"},
    "sources.cache": {"pl": "z pamięci podręcznej", "en": "from cache"},
    "sources.failed": {"pl": "niedostępne", "en": "unavailable"},
    "sources.page.intro": {
        "pl": "Serwis korzysta wyłącznie z oficjalnych, publicznych interfejsów. Odpowiedzi są "
        "buforowane w bazie, aby nie przekraczać limitów.",
        "en": "Only official public APIs are used. Responses are cached in the database to stay "
        "within the published limits.",
    },
    "sources.status": {"pl": "Stan", "en": "Status"},
    "sources.requests": {"pl": "Zapytania dziś", "en": "Requests today"},
    "sources.errors": {"pl": "Błędy dziś", "en": "Errors today"},
    "sources.last_ok": {"pl": "Ostatni sukces", "en": "Last success"},
    "sources.budget": {"pl": "Pozostały limit dzienny", "en": "Daily budget left"},
    "sources.cached": {"pl": "Odpowiedzi w buforze", "en": "Cached responses"},
    "sources.terms": {"pl": "Warunki", "en": "Terms"},
    "sources.limits": {"pl": "Limity", "en": "Limits"},
    "sources.docs": {"pl": "dokumentacja", "en": "documentation"},
    "sources.bzp_coverage": {"pl": "Pokrycie BZP", "en": "BZP coverage"},
    "sources.days": {"pl": "dni", "en": "days"},
    "status.ok": {"pl": "działa", "en": "ok"},
    "status.degraded": {"pl": "z błędami", "en": "degraded"},
    "status.down": {"pl": "niedostępne", "en": "down"},
    "status.unknown": {"pl": "brak danych", "en": "no data"},
    "footer.disclaimer": {
        "pl": "Dane mają charakter informacyjny. Wiążące są wyłącznie odpisy i zaświadczenia "
        "wydawane przez rejestry. Projekt niezależny, niezwiązany z administracją publiczną.",
        "en": "Information only. Only extracts and certificates issued by the registries are "
        "authoritative. Independent project, not affiliated with any public authority.",
    },
    "error.not_found": {"pl": "Nie znaleziono firmy.", "en": "Company not found."},
    "error.unavailable": {
        "pl": "Rejestry są chwilowo niedostępne. Spróbuj ponownie za chwilę.",
        "en": "The registries are temporarily unavailable. Please try again shortly.",
    },
    "field.name": {"pl": "Nazwa", "en": "Name"},
    "field.legal_form": {"pl": "Forma prawna", "en": "Legal form"},
    "field.address": {"pl": "Adres", "en": "Address"},
    "field.website": {"pl": "Strona WWW", "en": "Website"},
    "field.share_capital": {"pl": "Kapitał zakładowy", "en": "Share capital"},
    "field.krs_last_entry": {"pl": "Wpis w KRS", "en": "KRS entry"},
    "field.krs_deregistered_on": {"pl": "Wykreślenie z KRS", "en": "Removal from KRS"},
    "field.representation_rule": {"pl": "Sposób reprezentacji", "en": "Representation"},
    "field.management": {"pl": "Zarząd", "en": "Management board"},
    "field.supervisory_board": {"pl": "Organ nadzoru", "en": "Supervisory body"},
    "field.proxies": {"pl": "Prokura", "en": "Commercial proxy"},
    "field.main_activity": {"pl": "Przeważające PKD", "en": "Main PKD"},
    "field.vat_status": {"pl": "Status VAT", "en": "VAT status"},
    "field.vat_accounts": {"pl": "Rachunek na białej liście", "en": "White list bank account"},
    "field.vat_working_address": {"pl": "Adres działalności (VAT)", "en": "Business address (VAT)"},
    "search.title": {
        "pl": "Sprawdź firmę w rejestrach publicznych",
        "en": "Look up a company in Polish public registries",
    },
    "search.lead": {
        "pl": "Dane z KRS, białej listy VAT i Biuletynu Zamówień Publicznych w jednym miejscu, "
        "z historią zmian zapisywaną przy każdym sprawdzeniu.",
        "en": "KRS, the VAT white list and the Public Procurement Bulletin in one place, with a "
        "change history recorded on every check.",
    },
    "block.entity": {"pl": "Dane podmiotu", "en": "Entity"},
    "block.representation": {"pl": "Reprezentacja", "en": "Representation"},
    "block.activity": {"pl": "Przedmiot działalności", "en": "Business activity"},
    "block.vat": {"pl": "Status VAT i rachunki", "en": "VAT status and bank accounts"},
    "rail.section": {"pl": "dział", "en": "section"},
    "rail.whitelist": {"pl": "Biała lista", "en": "White list"},
    "rail.whitelist.sub": {"pl": "Ministerstwo Finansów", "en": "Ministry of Finance"},
    "rail.bzp.sub": {"pl": "ogłoszenia o wyniku", "en": "award notices"},
    "registry.P": {"pl": "Rejestr przedsiębiorców", "en": "Register of businesses"},
    "registry.S": {"pl": "Rejestr stowarzyszeń", "en": "Register of associations"},
    "company.since": {"pl": "od", "en": "since"},
    "company.suspended": {"pl": "zawieszony", "en": "suspended"},
    "company.more_accounts": {"pl": "i jeszcze", "en": "and"},
    "company.more_accounts.tail": {"pl": "rachunków", "en": "more"},
    "back": {"pl": "Wróć do wyszukiwania", "en": "Back to search"},
}


def translate(key: str, lang: Lang) -> str:
    entry = TEXTS.get(key)
    if entry is None:
        return key
    return entry.get(lang) or entry["pl"]
