"""Category: SEC EDGAR Form 4 (insider transaction) provider methods --
`fetch_form4_filing_list`, `fetch_form4_index`, `select_form4_primary_document`,
`fetch_form4_document`, `normalize_form4_document` (Session 36 continued,
ADR-0086). Mirrors `test_sec_edgar_provider.py`'s discipline: the real
network is never called here, only a stub transport.

**Evidence tier note**: unlike the rest of `test_sec_edgar_provider.py`'s
fixtures (Tier 2, documentation-shaped only), `_REAL_FORM4_XML` below is
the ACTUAL XML text captured from one real EDGAR filing this session
(AAPL, accession 0001140361-26-035636, Jennifer Newstead SVP GC and
Government Affairs, Rule 10b5-1 sale) -- verified byte-for-byte against
`normalize_form4_document`'s real output before this test file was
written, per `sec_edgar.py`'s own Tier 1 labeling for this method. The
Atom feed and index.json fixtures reconstruct the real, directly-observed
response shape (same two endpoints, same real accession number) but are
not the literal captured bytes, matching this project's existing
`_SAMPLE_COMPANY_FACTS`-style convention for documented-shape fixtures."""

from __future__ import annotations

from helpers import utc

from data_infra.providers.sec_edgar import SecEdgarFundamentalsProvider
from data_infra.providers.sec_edgar_config import SecEdgarConfig
from data_infra.providers.sec_edgar_transport import SecEdgarTransportResponse

_REAL_FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>

    <schemaVersion>X0609</schemaVersion>

    <documentType>4</documentType>

    <periodOfReport>2026-09-01</periodOfReport>

    <issuer>
        <issuerCik>0000320193</issuerCik>
        <issuerName>Apple Inc.</issuerName>
        <issuerTradingSymbol>AAPL</issuerTradingSymbol>
        <issuerForeignTradingSymbol></issuerForeignTradingSymbol>
    </issuer>

    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>0001780525</rptOwnerCik>
            <rptOwnerName>Newstead Jennifer</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerAddress>
            <rptOwnerNonUSAddressFlag>false</rptOwnerNonUSAddressFlag>
            <rptOwnerStreet1>ONE APPLE PARK WAY</rptOwnerStreet1>
            <rptOwnerStreet2></rptOwnerStreet2>
            <rptOwnerCity>CUPERTINO</rptOwnerCity>
            <rptOwnerState>CA</rptOwnerState>
            <rptOwnerZipCode>95014</rptOwnerZipCode>
            <rptOwnerStateDescription></rptOwnerStateDescription>
        </reportingOwnerAddress>
        <reportingOwnerRelationship>
            <isOfficer>true</isOfficer>
            <officerTitle>SVP, GC and Government Affairs</officerTitle>
        </reportingOwnerRelationship>
    </reportingOwner>

    <aff10b5One>true</aff10b5One>

    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <securityTitle>
                <value>Common Stock</value>
                <footnoteId id="F1"/>
            </securityTitle>
            <transactionDate>
                <value>2026-09-01</value>
            </transactionDate>
            <transactionCoding>
                <transactionFormType>4</transactionFormType>
                <transactionCode>S</transactionCode>
                <equitySwapInvolved>0</equitySwapInvolved>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares>
                    <value>1439</value>
                </transactionShares>
                <transactionPricePerShare>
                    <value>317.01</value>
                </transactionPricePerShare>
                <transactionAcquiredDisposedCode>
                    <value>D</value>
                </transactionAcquiredDisposedCode>
            </transactionAmounts>
            <postTransactionAmounts>
                <sharesOwnedFollowingTransaction>
                    <value>35790</value>
                </sharesOwnedFollowingTransaction>
            </postTransactionAmounts>
            <ownershipNature>
                <directOrIndirectOwnership>
                    <value>D</value>
                </directOrIndirectOwnership>
            </ownershipNature>
        </nonDerivativeTransaction>
    </nonDerivativeTable>

    <footnotes>
        <footnote id="F1">This transaction was made pursuant to a Rule 10b5-1 trading plan adopted by the reporting person on May 5, 2026.</footnote>
    </footnotes>

    <ownerSignature>
        <signatureName>/s/ Sam Whittington, Attorney-in-Fact for Jennifer Newstead</signatureName>
        <signatureDate>2026-09-03</signatureDate>
    </ownerSignature>
</ownershipDocument>
"""

_REAL_SHAPE_ATOM_FEED = """<?xml version="1.0" encoding="ISO-8859-1"?>
<feed xmlns="http://www.w3.org/2005/Atom">
    <entry>
        <title>4 - Apple Inc. (0000320193) (Issuer)</title>
        <link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/320193/000114036126035636/"/>
        <updated>2026-09-03T18:02:11-04:00</updated>
        <content type="text/xml">
            <accession-number>0001140361-26-035636</accession-number>
            <filing-date>2026-09-03</filing-date>
            <filing-type>4</filing-type>
            <filing-href>https://www.sec.gov/Archives/edgar/data/320193/000114036126035636/</filing-href>
        </content>
    </entry>
    <entry>
        <title>4 - Apple Inc. (0000320193) (Issuer)</title>
        <link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/320193/000114036126030001/"/>
        <updated>2026-06-02T09:10:00-04:00</updated>
        <content type="text/xml">
            <accession-number>0001140361-26-030001</accession-number>
            <filing-date>2026-06-02</filing-date>
            <filing-type>4</filing-type>
            <filing-href>https://www.sec.gov/Archives/edgar/data/320193/000114036126030001/</filing-href>
        </content>
    </entry>
</feed>
"""

_REAL_SHAPE_INDEX_JSON = {
    "directory": {
        "item": [
            {"name": "form4.xml", "type": "form4.xml", "size": "3153"},
            {"name": "0001140361-26-035636-index.htm", "type": "text.gif", "size": "3210"},
            {"name": "R1.htm", "type": "text.gif", "size": "1024"},  # XBRL-viewer rendering fragment -- must be excluded
        ]
    }
}


def _provider() -> SecEdgarFundamentalsProvider:
    return SecEdgarFundamentalsProvider(SecEdgarConfig(), transport=None)  # transport unused where a stub is passed explicitly


class TestFetchForm4FilingList:
    def test_builds_the_correct_www_host_path(self) -> None:
        calls = []

        class _StubTransport:
            def get(self, path, *, timeout):
                calls.append(path)
                return SecEdgarTransportResponse(status_code=200, body=None, raw_text=_REAL_SHAPE_ATOM_FEED, headers={})

        provider = _provider()
        provider.fetch_form4_filing_list("0000320193", _StubTransport())
        assert calls == [
            "/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193&type=4&dateb=&owner=include&count=40&output=atom"
        ]

    def test_parses_every_entry(self) -> None:
        class _StubTransport:
            def get(self, path, *, timeout):
                return SecEdgarTransportResponse(status_code=200, body=None, raw_text=_REAL_SHAPE_ATOM_FEED, headers={})

        provider = _provider()
        filings = provider.fetch_form4_filing_list("0000320193", _StubTransport())
        assert len(filings) == 2
        assert filings[0]["accession_number"] == "0001140361-26-035636"
        assert filings[0]["filing_date"] == utc(2026, 9, 3)
        assert filings[0]["filing_href"].endswith("000114036126035636/")

    def test_before_date_is_passed_through_as_the_dateb_query_param(self) -> None:
        # ADR-0088: pagination relies on this parameter actually
        # reaching EDGAR's dateb query field.
        calls = []

        class _StubTransport:
            def get(self, path, *, timeout):
                calls.append(path)
                return SecEdgarTransportResponse(status_code=200, body=None, raw_text=_REAL_SHAPE_ATOM_FEED, headers={})

        provider = _provider()
        provider.fetch_form4_filing_list("0000320193", _StubTransport(), before_date="2023-06-01")
        assert calls == [
            "/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193&type=4&dateb=2023-06-01&owner=include&count=40&output=atom"
        ]

    def test_before_date_none_omits_the_dateb_value_exactly_as_before(self) -> None:
        # Backward-compatible default -- no before_date reproduces the
        # exact pre-ADR-0088 single-page query shape.
        calls = []

        class _StubTransport:
            def get(self, path, *, timeout):
                calls.append(path)
                return SecEdgarTransportResponse(status_code=200, body=None, raw_text=_REAL_SHAPE_ATOM_FEED, headers={})

        provider = _provider()
        provider.fetch_form4_filing_list("0000320193", _StubTransport())
        assert calls == [
            "/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193&type=4&dateb=&owner=include&count=40&output=atom"
        ]

    def test_empty_response_yields_no_filings_not_an_error(self) -> None:
        class _StubTransport:
            def get(self, path, *, timeout):
                return SecEdgarTransportResponse(status_code=200, body=None, raw_text="", headers={})

        provider = _provider()
        assert provider.fetch_form4_filing_list("0000320193", _StubTransport()) == []

    def test_entry_missing_accession_number_is_skipped_not_fabricated(self) -> None:
        incomplete = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
    <entry>
        <content type="text/xml">
            <filing-date>2026-09-03</filing-date>
        </content>
    </entry>
</feed>
"""

        class _StubTransport:
            def get(self, path, *, timeout):
                return SecEdgarTransportResponse(status_code=200, body=None, raw_text=incomplete, headers={})

        provider = _provider()
        assert provider.fetch_form4_filing_list("0000320193", _StubTransport()) == []


class TestFetchForm4Index:
    def test_builds_the_non_zero_padded_cik_path(self) -> None:
        # A real, directly-observed difference from the XBRL companyfacts
        # path template -- this CIK must NOT be zero-padded here.
        calls = []

        class _StubTransport:
            def get(self, path, *, timeout):
                calls.append(path)
                return SecEdgarTransportResponse(status_code=200, body=_REAL_SHAPE_INDEX_JSON, raw_text=None, headers={})

        provider = _provider()
        provider.fetch_form4_index("0000320193", "0001140361-26-035636", _StubTransport())
        assert calls == ["/Archives/edgar/data/320193/000114036126035636/index.json"]

    def test_returns_the_parsed_index(self) -> None:
        class _StubTransport:
            def get(self, path, *, timeout):
                return SecEdgarTransportResponse(status_code=200, body=_REAL_SHAPE_INDEX_JSON, raw_text=None, headers={})

        provider = _provider()
        result = provider.fetch_form4_index("0000320193", "0001140361-26-035636", _StubTransport())
        assert result == _REAL_SHAPE_INDEX_JSON

    def test_unexpected_shape_raises_permanent_provider_error(self) -> None:
        from data_infra.provider import PermanentProviderError
        import pytest

        class _StubTransport:
            def get(self, path, *, timeout):
                return SecEdgarTransportResponse(status_code=200, body=["not", "a", "dict"], raw_text=None, headers={})

        provider = _provider()
        with pytest.raises(PermanentProviderError):
            provider.fetch_form4_index("0000320193", "0001140361-26-035636", _StubTransport())


class TestSelectForm4PrimaryDocument:
    def test_picks_the_first_real_xml_file(self) -> None:
        provider = _provider()
        assert provider.select_form4_primary_document(_REAL_SHAPE_INDEX_JSON) == "form4.xml"

    def test_excludes_xbrl_viewer_rendering_fragments(self) -> None:
        index = {"directory": {"item": [{"name": "R1.htm"}, {"name": "R2.htm"}]}}
        provider = _provider()
        assert provider.select_form4_primary_document(index) is None

    def test_no_items_returns_none_not_an_error(self) -> None:
        provider = _provider()
        assert provider.select_form4_primary_document({}) is None


class TestFetchForm4Document:
    def test_builds_the_correct_document_path(self) -> None:
        calls = []

        class _StubTransport:
            def get(self, path, *, timeout):
                calls.append(path)
                return SecEdgarTransportResponse(status_code=200, body=None, raw_text=_REAL_FORM4_XML, headers={})

        provider = _provider()
        provider.fetch_form4_document("0000320193", "0001140361-26-035636", "form4.xml", _StubTransport())
        assert calls == ["/Archives/edgar/data/320193/000114036126035636/form4.xml"]

    def test_empty_response_raises_permanent_provider_error(self) -> None:
        from data_infra.provider import PermanentProviderError
        import pytest

        class _StubTransport:
            def get(self, path, *, timeout):
                return SecEdgarTransportResponse(status_code=200, body=None, raw_text="", headers={})

        provider = _provider()
        with pytest.raises(PermanentProviderError):
            provider.fetch_form4_document("0000320193", "0001140361-26-035636", "form4.xml", _StubTransport())


class TestNormalizeForm4Document:
    """Verified byte-for-byte against `_REAL_FORM4_XML` (the actual
    captured AAPL filing) before this test file existed -- see this
    module's own docstring."""

    def _transactions(self):
        provider = _provider()
        return provider.normalize_form4_document(
            "AAPL", _REAL_FORM4_XML,
            accession_number="0001140361-26-035636",
            filing_date=utc(2026, 9, 3),
            retrieved_at=utc(2026, 9, 5),
            ingestion_time=utc(2026, 9, 5),
        )

    def test_parses_exactly_one_non_derivative_transaction(self) -> None:
        txns = self._transactions()
        assert len(txns) == 1

    def test_reporting_owner_fields(self) -> None:
        txn = self._transactions()[0]
        assert txn.reporting_owner_name == "Newstead Jennifer"
        assert txn.reporting_owner_cik == "0001780525"
        assert txn.is_officer is True
        assert txn.is_director is False
        assert txn.is_ten_percent_owner is False
        assert txn.officer_title == "SVP, GC and Government Affairs"

    def test_transaction_fields(self) -> None:
        txn = self._transactions()[0]
        assert txn.transaction_code == "S"
        assert txn.shares == 1439.0
        assert txn.price_per_share == 317.01
        assert txn.acquired_disposed_code == "D"
        assert txn.transaction_date == utc(2026, 9, 1)

    def test_is_10b5_1_plan_is_true_for_this_real_sample(self) -> None:
        # The real, concrete discovery that motivated this field's
        # existence: this sample is a pre-scheduled Rule 10b5-1 sale,
        # not a genuinely discretionary trade.
        txn = self._transactions()[0]
        assert txn.is_10b5_1_plan is True

    def test_available_time_is_the_filing_date_not_the_transaction_date(self) -> None:
        txn = self._transactions()[0]
        assert txn.available_time == utc(2026, 9, 3)
        assert txn.available_time != txn.transaction_date

    def test_security_id_is_the_caller_supplied_symbol_not_parsed_from_the_document(self) -> None:
        txn = self._transactions()[0]
        assert txn.security_id == "AAPL"

    def test_accession_number_is_attached_to_every_row(self) -> None:
        txn = self._transactions()[0]
        assert txn.accession_number == "0001140361-26-035636"

    def test_missing_reporting_owner_yields_no_transactions_not_an_error(self) -> None:
        no_owner_xml = "<ownershipDocument><nonDerivativeTable/></ownershipDocument>"
        provider = _provider()
        txns = provider.normalize_form4_document(
            "AAPL", no_owner_xml, accession_number="X", filing_date=utc(2026, 9, 3),
            retrieved_at=utc(2026, 9, 5), ingestion_time=utc(2026, 9, 5),
        )
        assert txns == []

    def test_missing_non_derivative_table_yields_no_transactions_not_an_error(self) -> None:
        no_table_xml = """<ownershipDocument>
            <reportingOwner>
                <reportingOwnerId><rptOwnerCik>0001780525</rptOwnerCik><rptOwnerName>X</rptOwnerName></reportingOwnerId>
            </reportingOwner>
        </ownershipDocument>"""
        provider = _provider()
        txns = provider.normalize_form4_document(
            "AAPL", no_table_xml, accession_number="X", filing_date=utc(2026, 9, 3),
            retrieved_at=utc(2026, 9, 5), ingestion_time=utc(2026, 9, 5),
        )
        assert txns == []

    def test_row_missing_required_field_is_skipped_not_fabricated(self) -> None:
        incomplete_row_xml = """<ownershipDocument>
            <reportingOwner>
                <reportingOwnerId><rptOwnerCik>0001780525</rptOwnerCik><rptOwnerName>X</rptOwnerName></reportingOwnerId>
            </reportingOwner>
            <nonDerivativeTable>
                <nonDerivativeTransaction>
                    <transactionDate><value>2026-09-01</value></transactionDate>
                    <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
                </nonDerivativeTransaction>
            </nonDerivativeTable>
        </ownershipDocument>"""
        # transactionAmounts entirely missing -- must be skipped, not crash.
        provider = _provider()
        txns = provider.normalize_form4_document(
            "AAPL", incomplete_row_xml, accession_number="X", filing_date=utc(2026, 9, 3),
            retrieved_at=utc(2026, 9, 5), ingestion_time=utc(2026, 9, 5),
        )
        assert txns == []

    def test_derivative_table_is_not_parsed(self) -> None:
        # Deliberate scope limit -- see normalize_form4_document's own docstring.
        with_derivative = _REAL_FORM4_XML.replace(
            "</nonDerivativeTable>",
            "</nonDerivativeTable><derivativeTable><derivativeTransaction/></derivativeTable>",
        )
        provider = _provider()
        txns = provider.normalize_form4_document(
            "AAPL", with_derivative, accession_number="0001140361-26-035636", filing_date=utc(2026, 9, 3),
            retrieved_at=utc(2026, 9, 5), ingestion_time=utc(2026, 9, 5),
        )
        assert len(txns) == 1  # only the one non-derivative row, derivative row ignored

    def test_second_row_gets_a_distinct_source_record_id(self) -> None:
        two_row_xml = _REAL_FORM4_XML.replace(
            "</nonDerivativeTransaction>\n    </nonDerivativeTable>",
            "</nonDerivativeTransaction>\n"
            "        <nonDerivativeTransaction>"
            "<transactionDate><value>2026-09-02</value></transactionDate>"
            "<transactionCoding><transactionCode>S</transactionCode></transactionCoding>"
            "<transactionAmounts>"
            "<transactionShares><value>500</value></transactionShares>"
            "<transactionPricePerShare><value>320.00</value></transactionPricePerShare>"
            "<transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>"
            "</transactionAmounts>"
            "</nonDerivativeTransaction>\n    </nonDerivativeTable>",
        )
        provider = _provider()
        txns = provider.normalize_form4_document(
            "AAPL", two_row_xml, accession_number="0001140361-26-035636", filing_date=utc(2026, 9, 3),
            retrieved_at=utc(2026, 9, 5), ingestion_time=utc(2026, 9, 5),
        )
        assert len(txns) == 2
        ids = {t.provenance.source_record_id for t in txns}
        assert len(ids) == 2
