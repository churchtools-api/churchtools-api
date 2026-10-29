"""Test data for GET endpoints that a fresh demo has nothing for.

`create(client)` adds the data before `test_read.py` runs and tells the resolver
where to find it (`Seed.paths`, `Seed.queries`). Every step is independent: if one
fails, its reason ends up in the results and the others still run. `Seed.remove()`
deletes everything again and restores changed settings, in reverse order.

Side effects worth knowing on a real instance: enabling QR check-in creates
tickets for the members, and the sync module and an eUBP business number are
switched on temporarily.
"""

from __future__ import annotations

import datetime as dt
import functools
import json
import typing as _t
import uuid

import churchtools_rs as ct

PREFIX = "ctrs-test"

# A minimal CAMT.053 bank statement (version 001.02; .04 and .08 are rejected as
# "File format not supported", the MT940 parser found no statement in simple files).
CAMT = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt>
<GrpHdr><MsgId>CTRS1</MsgId><CreDtTm>{d0}T10:00:00</CreDtTm></GrpHdr>
<Stmt><Id>CTRS-1</Id><CreDtTm>{d0}T10:00:00</CreDtTm>
<Acct><Id><IBAN>DE89370400440532013000</IBAN></Id><Ccy>EUR</Ccy></Acct>
<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">1000.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{d0}</Dt></Dt></Bal>
<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">1050.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{d1}</Dt></Dt></Bal>
<Ntry><Amt Ccy="EUR">50.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts>BOOK</Sts><BookgDt><Dt>{d1}</Dt></BookgDt>
<ValDt><Dt>{d1}</Dt></ValDt><BkTxCd/><NtryDtls><TxDtls><RmtInf><Ustrd>Spende ctrs-test</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
</Stmt></BkToCstmrStmt></Document>"""


class Seed:
    def __init__(self, client: _t.Any) -> None:
        self.client = client
        self.core = client.recorder.core  # unrecorded: seeding is not what is tested
        # (path template, wire name) -> value for path parameters
        self.paths: dict[tuple[str, str], _t.Any] = {}
        # (path template, Python name) -> value for query parameters
        self.queries: dict[tuple[str, str], _t.Any] = {}
        self.failed: dict[str, str] = {}
        self._undo: list[tuple[str, _t.Callable[[], object]]] = []

    # --- helpers ------------------------------------------------------------------

    def raw(self, method: str, path: str, body: _t.Any = None, query: list[tuple[str, str]] | None = None) -> _t.Any:
        data = self.core.request(method, path, query or [], json.dumps(body) if body is not None else None)
        return json.loads(data) if data.strip() else None

    def undo(self, label: str, step: _t.Callable[[], object]) -> None:
        self._undo.append((label, step))

    def step(self, name: str, fn: _t.Callable[[], None]) -> None:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - recorded and reported, see failed
            self.failed[name] = f"{type(e).__name__}: {e}"[:300]

    def remove(self) -> dict[str, str]:
        """Undoes all steps; returns the undo steps that failed."""
        errors = {}
        for label, step in reversed(self._undo):
            try:
                step()
            except ct.NotFound:
                pass
            except Exception as e:  # noqa: BLE001
                errors[label] = f"{type(e).__name__}: {e}"[:300]
        return errors

    def group(self, name: str) -> int:
        md = self.client.person.get_master_data()
        group = self.client.groups.create(
            name=f"{PREFIX} {name} {uuid.uuid4().hex[:6]}",
            group_type_id=md.group_types[0].id,
            group_status_id=md.group_statuses[0].id,
        )
        self.undo(f"group {group.id}", lambda: self.client.groups.delete(group.id))
        return _t.cast(int, group.id)

    # --- the steps -----------------------------------------------------------------

    def group_with_activity(self) -> None:
        """Meeting, QR check-in tickets, membership documents, dynamic-group rules."""
        c, me = self.client, self.me
        gid = self.group("Seed-Gruppe")
        c.groups.members.update(gid, me)
        meeting = c.groups.meetings.create(gid, start_date=dt.datetime.now(dt.timezone.utc).replace(microsecond=0))
        for path in ("/groups/{groupId}/meetings/{meetingId}", "/groups/{groupId}/meetings/{meetingId}/members"):
            self.paths[(path, "groupId")] = gid
            self.paths[(path, "meetingId")] = meeting.id

        # Enabling QR check-in creates a ticket for every member.
        c.groups.patch(gid, extra_body={"qrCodeCheckin": True})
        for path in ("/groups/{groupId}/qrcodecheckin/{personId}", "/groups/{groupId}/qrcodecheckin/{personId}/pdf"):
            self.paths[(path, "groupId")] = gid
            self.paths[(path, "personId")] = me

        c.dynamic_groups.update_status(gid, dynamic_group_status="manual")
        rule = {
            "description": f"{PREFIX}: nur Person {me}",
            "shorty": "T",
            "importance": 10,
            "personIdFieldName": "person.id",
            "query": {
                "method": "ChurchQuery",
                "params": {"primaryEntityAlias": "person", "responseFields": ["person.id"], "filter": {"==": [{"var": "person.id"}, me]}},
            },
            "process": {"groupOnly": {}, "groupAndQueryResult": {}, "queryResultOnly": {}},
        }
        c.dynamic_groups.update_ruleset(gid, dynamic_group_rule_set=[rule])
        self.undo("dynamic ruleset", lambda: c.dynamic_groups.delete_ruleset(gid))
        for path in ("/dynamicgroups/{groupId}/ruleset", "/dynamicgroups/{groupId}/status"):
            self.paths[(path, "groupId")] = gid

        self.step("membership document template", lambda: self.document_template(gid))

    def document_template(self, gid: int) -> None:
        c, me = self.client, self.me
        template = c.html_templates.create(domain_type="groupmember-document", name=f"{PREFIX} Bescheinigung", is_global=True)
        self.undo("html template", lambda: c.html_templates.delete(template.id, dry_run=False))
        # Documents are available for roles that list the template, and only to group leaders.
        leader = next(r for r in c.groups.roles.list(gid) if r.is_leader)
        c.groups.roles.patch(gid, leader.id, html_template_ids=[template.id])
        self.undo("role templates", lambda: c.groups.roles.patch(gid, leader.id, html_template_ids=[]))
        c.groups.members.update(gid, me, group_type_role_id=leader.group_type_role_id)
        self.paths[("/groups/{groupId}/documents/{htmlTemplateId}", "groupId")] = gid
        self.paths[("/groups/{groupId}/documents/{htmlTemplateId}", "htmlTemplateId")] = template.id
        path = "/groups/{groupId}/members/{memberId}/documents/{htmlTemplateId}"
        self.paths[(path, "groupId")] = gid
        self.paths[(path, "memberId")] = me
        self.paths[(path, "htmlTemplateId")] = template.id

    def public_signup(self) -> None:
        """A public group with open signup and a signup token."""
        c, me = self.client, self.me
        gid = self.group("Anmeldung")
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        c.groups.patch(
            gid,
            extra_body={
                "visibility": "public",
                "signUpOpeningDate": (now - dt.timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                "signUpClosingDate": (now + dt.timedelta(days=30)).isoformat().replace("+00:00", "Z"),
            },
        )
        token = c.public_groups.token(gid, person_id=me)
        for path in ("/publicgroups/{groupId}/form", "/publicgroups/{groupId}/possiblerequesters"):
            self.paths[(path, "groupId")] = gid
            self.queries[(path, "token")] = token.token

    def person_data(self) -> None:
        """A file, an absence and an app device for the current user."""
        c, me = self.client, self.me
        uploaded = c.files.create("person", me, files=[ct.Upload(f"{PREFIX}.txt", b"Testdatei von churchtools-rs")])
        for f in uploaded:
            self.undo(f"file {f.id}", functools.partial(c.files.delete, f.id))
        reason = c.event.get_master_data().absence_reasons[0].id
        absence = c.persons.absences.create(me, absence_reason_id=reason, start_date=dt.date.today(), end_date=dt.date.today())
        self.undo("absence", lambda: c.persons.absences.delete(me, absence.id))
        c.persons.devices.update(me, f"{PREFIX}-device", type_="FCM")
        self.undo("device", lambda: c.persons.devices.delete(me, f"{PREFIX}-device"))

    def further_link(self) -> None:
        c = self.client
        link = c.further_links.create(name=PREFIX, url="https://example.org", description=None, image_url=None, sort_key=999)
        self.undo("further link", lambda: c.further_links.delete(link.id))

    def post_comment(self) -> None:
        c = self.client
        post = c.posts.list()[0]
        comment = c.posts.comments.create(post.id, post_id_2=post.id, content=f"{PREFIX} Kommentar")
        self.undo("comment", lambda: c.posts.comments.delete(post.id, comment.id))
        c.posts.comments.reactions.update(post.id, comment.id, emoji="👍")
        self.paths[("/posts/{postId}/comments/{commentId}/reactions", "postId")] = post.id
        self.paths[("/posts/{postId}/comments/{commentId}/reactions", "commentId")] = comment.id

    def finance(self) -> None:
        c = self.client
        period = c.finance.accounting_periods.list()[0].id
        accounts = c.finance.accounts.list(accounting_period_id=period)
        discount = c.finance.cash_discounts.create(account_id=accounts[0].id, note=PREFIX, rate=2)
        self.undo("cash discount", lambda: c.finance.cash_discounts.delete(discount.id, dry_run=False))
        split = self.raw(
            "POST",
            "/finance/splittransactions",
            {
                "amount": 3000,
                "documentDate": f"{c.finance.accounting_periods.get(period).start_date}",
                "documentNumber": f"{PREFIX}-{uuid.uuid4().hex[:4]}",
                "note": PREFIX,
                "splitChildren": [
                    {"accountId": accounts[1].id, "contraAccountId": accounts[0].id, "amount": 1000, "note": "Teil 1"},
                    {"accountId": accounts[2].id, "contraAccountId": accounts[0].id, "amount": 2000, "note": "Teil 2"},
                ],
            },
        )["data"]
        self.undo("split transaction", lambda: c.finance.split_transactions.delete(split["id"]))
        self.paths[("/finance/splittransactions/{id}", "id")] = split["id"]
        self.step("bill", lambda: self.bill(period, split["id"]))
        self.step("eUBP submission", lambda: self.eubp(period))
        self.step("bank statement", lambda: self.statement(period, accounts[0].id))

    def eubp(self, period: int) -> None:
        c = self.client
        client = c.finance.clients.get(c.finance.accounting_periods.get(period).client_id)
        if not client.eubp_business_number:
            # A valid German Betriebsnummer (8 digits, check digit); restored afterwards.
            self._update_finance_client(client, "12345671", f"{PREFIX} GmbH")
            self.undo("eUBP business number", lambda: self._update_finance_client(client, None, None))
        submission = c.finance.eubp.submissions.create(client_id=client.id, transmission_reason=1, year_from=2024, year_to=2024)
        self.undo("eUBP submission", lambda: c.finance.eubp.submissions.delete(submission.id))

    def _update_finance_client(self, client: _t.Any, number: str | None, name: str | None) -> None:
        self.client.finance.clients.update(
            client.id,
            name=client.name,
            sort_key=client.sort_key,
            street=client.street,
            postal_code=client.postal_code,
            city=client.city,
            phone=client.phone,
            treasurer_id=client.treasurer_id,
            eubp_business_number=number,
            eubp_business_name=name,
        )

    def bill(self, period: int, split_id: int) -> None:
        c = self.client
        receipt = c.files.create("person", self.me, files=[ct.Upload(f"{PREFIX}-beleg.txt", b"Quittung")])[0]
        self.undo("bill source file", lambda: c.files.delete(receipt.id))
        bill = self.raw(
            "POST",
            "/finance/bills",
            {
                "accountingPeriodId": period,
                "fileId": receipt.id,
                "splitTransactionId": split_id,
                "transactionId": None,
                "transactionSuggestionId": None,
                "submittedDate": str(dt.date.today()),
                "submittedPid": self.me,
            },
        )["data"]
        self.undo("bill", lambda: self.raw("DELETE", f"/finance/bills/{bill['id']}"))
        self.paths[("/finance/bills/{id}", "id")] = bill["id"]

    def statement(self, period: int, account_id: int) -> None:
        c = self.client
        start = c.finance.accounting_periods.get(period).start_date
        camt = CAMT.format(d0=start, d1=start + dt.timedelta(days=1)).encode()
        upload = ct.Upload(f"{PREFIX}-auszug.xml", camt, "text/xml")
        c.finance.accounting_periods.statements.preview(period, files=[upload])
        # Importing means uploading the file to the account's statement files.
        c.files.create("statement", account_id, files=[upload])
        statement = next(s for s in c.finance.accounting_periods.accounts.statements.list(period, account_id) if s.name == upload.filename)
        # Deleting the statement deletes its file too.
        self.undo("bank statement", lambda: c.finance.accounting_periods.statements.delete(period, statement.id))
        path = "/finance/accountingperiods/{id}/accounts/{accountId}/statements/{statementId}/movements"
        self.paths[(path, "id")] = period
        self.paths[(path, "accountId")] = account_id
        self.paths[(path, "statementId")] = statement.id

    def sync(self) -> None:
        """Turns the sync module on and adds a connection with a job, mapping and conflict."""
        c, me = self.client, self.me
        if not self.raw("GET", "/config").get("churchsync_active"):
            self.raw("PUT", "/config", {"churchsync_active": True})
            self.undo("sync module", lambda: self.raw("PUT", "/config", {"churchsync_active": False}))
        system = c.sync.externalsystems.create(name=PREFIX, adapter="churchtools", access_header_values={})
        self.undo("sync connection", lambda: c.sync.externalsystems.delete(system.id))
        job = c.sync.externalsystems.job_configs.create(system.id, name=f"{PREFIX} Job", domain_type="person", auto_schedule_enabled=False)
        self.undo("sync job", lambda: c.sync.externalsystems.job_configs.delete(system.id, job.id))
        mapping = c.sync.entity_mappings.create(
            domain_type="person", domain_id=str(me), source_id=system.id, source_entity_id=f"{PREFIX}-1", status="synced"
        )
        self.undo("entity mapping", lambda: c.sync.entity_mappings.delete(mapping.id))
        # jobId is the GUID of a sync run, not the job configuration id.
        # Conflicts need the GUID of a real sync run, which only a running adapter produces.
        self.step(
            "sync conflict",
            lambda: c.sync.conflicts.create(
                job_id=str(uuid.uuid4()), entity_mapping_id=mapping.id, type_="update", data=[{"key": "field", "value": "email"}]
            ),
        )
        self.paths[("/sync/adapters/{adapterName}/proxy/{uri}", "adapterName")] = "churchtools"
        self.paths[("/sync/adapters/{adapterName}/proxy/{uri}", "uri")] = "health"
        self.paths[("/sync/externalsystems/{externalSystemId}/adapterproxy/{uri}", "uri")] = "health"
        self.paths[("/sync/externalsystems/{externalSystemId}/fieldmappings/{domainType}", "domainType")] = "person"
        self.paths[("/sync/externalsystems/{externalSystemId}/fieldmappings/{domainType}/nosuggestions", "domainType")] = "person"

    def external_logins(self) -> None:
        """A hidden OIDC and a hidden SAML provider (not usable for logins)."""
        c = self.client
        common = {
            "is_visible": False,
            "create_new_person": False,
            "has_registration": False,
            "update_data_on_login": False,
            "new_person_campus_id": None,
            "new_person_department_id": None,
            "new_person_status_id": None,
        }
        saml = self.raw(
            "POST",
            "/externallogins",
            {"name": f"{PREFIX} SAML", "type": "saml", "config": {}, **{_camel(k): v for k, v in common.items()}},
        )["data"]
        self.undo("SAML provider", lambda: c.external_logins.delete(saml["id"]))
        oidc = self.raw(
            "POST",
            "/externallogins",
            {
                "name": f"{PREFIX} OIDC",
                "type": "oidc",
                # clientSecret is required, although the spec lists only issuer and clientId.
                "config": {"issuer": "https://accounts.google.com", "clientId": PREFIX, "clientSecret": "unused"},
                **{_camel(k): v for k, v in common.items()},
            },
        )["data"]
        self.undo("OIDC provider", lambda: c.external_logins.delete(oidc["id"]))
        for path in ("saml/login", "saml/metadata", "saml/sls", "saml/test/{state}"):
            self.paths[(f"/externallogins/{{externalLoginId}}/{path}", "externalLoginId")] = saml["id"]
        for path in ("oidc/callback", "oidc/start", "oidc/test/{state}"):
            self.paths[(f"/externallogins/{{externalLoginId}}/{path}", "externalLoginId")] = oidc["id"]
        self.paths[("/externallogins/{externalLoginId}", "externalLoginId")] = oidc["id"]
        for path in ("/externallogins/{externalLoginId}/oidc/test/{state}", "/externallogins/{externalLoginId}/saml/test/{state}"):
            self.paths[(path, "state")] = "unknown-state"
        self.queries[("/externallogins/{externalLoginId}/oidc/callback", "state")] = "unknown-state"

    def run(self) -> None:
        self.me = _t.cast(int, self.client.whoami.get().id)
        for name, fn in (
            ("group with meeting, QR tickets and rules", self.group_with_activity),
            ("public signup", self.public_signup),
            ("person file, absence, device", self.person_data),
            ("further link", self.further_link),
            ("post comment", self.post_comment),
            ("finance", self.finance),
            ("sync", self.sync),
            ("external logins", self.external_logins),
        ):
            self.step(name, fn)


def _camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(p.title() for p in rest)


def create(client: _t.Any) -> Seed:
    seed = Seed(client)
    seed.run()
    return seed
