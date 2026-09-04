class DomainError(Exception):
    code = "domain_error"


class MissingInformationError(DomainError): code = "missing_information"
class AmbiguousRequestError(DomainError): code = "ambiguous_request"
class SupplierIneligibleError(DomainError): code = "supplier_ineligible"
class ToolTimeoutError(DomainError): code = "tool_timeout"
class InvalidModelOutputError(DomainError): code = "invalid_model_output"
class ProviderUnavailableError(DomainError): code = "provider_unavailable"
class PersistenceError(DomainError): code = "persistence_error"
class FileValidationError(DomainError): code = "file_validation"
class VersionConflictError(DomainError): code = "version_conflict"
