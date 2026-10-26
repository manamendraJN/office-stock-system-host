"""Errors raised by the service layer.

They mirror the HTTP-flavoured ApiError of the original Express API. Views turn them into
flash messages / form errors (or a 404 / 403 page); they never leak as a server error.
"""


class ServiceError(Exception):
    status = 400

    def __init__(self, message='Bad request', field_errors=None):
        super().__init__(message)
        self.message = message
        # {field_name: message}, used to attach the error to a form field when possible.
        self.field_errors = field_errors or {}

    def __str__(self):
        return self.message


class BadRequest(ServiceError):
    status = 400


class Unauthorized(ServiceError):
    status = 401

    def __init__(self, message='Please sign in', field_errors=None):
        super().__init__(message, field_errors)


class Forbidden(ServiceError):
    status = 403

    def __init__(self, message='You do not have permission to do this', field_errors=None):
        super().__init__(message, field_errors)


class NotFound(ServiceError):
    status = 404

    def __init__(self, message='Not found', field_errors=None):
        super().__init__(message, field_errors)


class Conflict(ServiceError):
    status = 409

    def __init__(self, message='Conflict', field_errors=None):
        super().__init__(message, field_errors)
