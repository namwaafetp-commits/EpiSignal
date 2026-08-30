from episignal_backend.ingestion.protocol import DiscoveryConnector, DiscoveryRepository


def test_discovery_protocols_are_runtime_checkable() -> None:
    class NotAConnector:
        pass

    assert not isinstance(NotAConnector(), DiscoveryConnector)
    assert not isinstance(NotAConnector(), DiscoveryRepository)


def test_retrieval_failed_is_distinct_from_unsupported() -> None:
    from episignal_backend.ingestion.protocol import RetrievalFailed, UnsupportedDocument

    assert not issubclass(RetrievalFailed, UnsupportedDocument)
    assert issubclass(RetrievalFailed, Exception)
