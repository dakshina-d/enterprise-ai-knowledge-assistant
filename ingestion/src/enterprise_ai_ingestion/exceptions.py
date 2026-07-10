"""Safe, typed offline-ingestion failures."""


class IngestionError(Exception):
    """Base failure whose message contains no source body content."""


class SourceManifestError(IngestionError):
    pass


class UnsafeSourcePathError(IngestionError):
    pass


class SourceFileMissingError(IngestionError):
    pass


class FrontMatterError(IngestionError):
    pass


class SourceHashMismatchError(IngestionError):
    pass


class UnsupportedMetadataError(IngestionError):
    pass


class MarkdownParseError(IngestionError):
    pass


class ChunkingError(IngestionError):
    pass


class ArtifactValidationError(IngestionError):
    pass


class ArtifactDriftError(IngestionError):
    pass


class TransactionalWriteError(IngestionError):
    pass
