"""Known outcomes on a fresh demo instance, each with the reason found.

See docs/testbericht.md for the full analysis.
"""

from __future__ import annotations

# Operations not called at all.
SKIP: dict[str, str] = {
    "get-externallogins-externalLoginId-saml-sls": "leitet den Browser zum Identity-Provider um; über die API nichts zu prüfen",
}

_SYNC = "Sync-Modul auf der Instanz nicht aktiv"

# operationId -> (HTTP status, explanation)
EXPECTED_ERRORS: dict[str, tuple[int, str]] = {
    # Bugs in ChurchTools 3.138.0, still present in 3.138.1
    "get-calendars-calendarId-appointments-appointmentId-ical": (
        500,
        "Serverfehler 'is no valid URI' bei jedem getesteten Termin",
    ),
    "get-dbfields-fieldId-options-metadata": (
        500,
        "PHP-TypeError in DbFieldOptionsService (quote_identifier(null)) bei Feld 132",
    ),
    "get-images-fileId-hash": (
        404,
        "Bilder liegen unter /images/…, nicht unter /api/images/…; die Spec führt die Route fälschlich in der API",
    ),
    "get-images-fileId-hash-queryParams": (404, "wie GET /images/{fileId}/{hash}"),
    # Permissions by design (called in test_write_more.py)
    "put-persons-personId-confidentialityagreement": (403, "nur die Person selbst kann annehmen, ein Admin nur widerrufen"),
    # Login providers created by seed.py are placeholders without a real identity provider
    "get-externallogins-id-oidc-start": (404, "Test-Anbieter ist versteckt und hat keinen echten OIDC-Client"),
    "get-externallogins-id-oidc-callback": (401, "Callback ohne laufenden OIDC-Login"),
    "get-externallogins-externalLoginId-saml-login": (404, "Test-Anbieter hat keine Identity-Provider-Metadaten"),
    # Not configured or no data on the demo
    "get-evangelischetermine-eventtypes": (500, "SoapFault: evangelische-termine.de nicht eingerichtet (500 statt 4xx)"),
    "get-externallogins-oidc-callback": (401, "Callback ohne laufenden OIDC-Login"),
    "get-finance-donators-receipts": (400, "noch keine Zuwendungsbestätigungen für die Buchungsperiode erstellt"),
    "get-saml-login": (404, "SAML ist nicht eingerichtet"),
    "get-saml-metadata": (404, "SAML ist nicht eingerichtet"),
    "get-sync-adapters": (401, _SYNC),
    "get-sync-externalsystems": (401, _SYNC),
    "get-sync-jobconfigs": (401, _SYNC),
    "get-sync-executions": (403, _SYNC),
    "get-sync-logs": (403, _SYNC),
}
