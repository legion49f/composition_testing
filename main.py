from collections.abc import Callable, Iterable
import enum
import dataclasses
import os
import logging
import time
from typing_extensions import Self

from composition_test.exceptions import (
    GetDeviceError,
    CheckModuleError,
    ImplementChangeError,
    PreCheckError,
    ActivationError,
    CloseChangeError,
    CancelChangeError,
    UploadArtifactsError,
    CreateIncidentError,
)

_LOGGER = logging.getLogger(__name__)

_ERROR_ON_GET_DEVICE = os.environ.get("ERROR_ON_GET_DEVICE", False)
_ERROR_ON_CHECK_MODULE = os.environ.get("ERROR_ON_CHECK_MODULE", False)
_ERROR_ON_IMPLEMENT_CHANGE = os.environ.get("ERROR_ON_IMPLEMENT_CHANGE", False)
_ERROR_ON_PRE_CHECKS = os.environ.get("ERROR_ON_PRE_CHECKS", False)
_ERROR_ON_ACTIVATION = os.environ.get("ERROR_ON_ACTIVATION", False)
_ERROR_ON_CLOSE_CHANGE = os.environ.get("ERROR_ON_CLOSE_CHANGE", False)
_ERROR_ON_UPLOAD_ARTIFACTS = os.environ.get("ERROR_ON_UPLOAD_ARTIFACTS", False)
_ERROR_ON_CREATE_INCIDENT = os.environ.get("ERROR_ON_CREATE_INCIDENT", False)
_ERROR_ON_CANCEL_CHANGE = os.environ.get("ERROR_ON_CANCEL_CHANGE", False)


class ChangeState(enum.IntEnum):
    NEW = enum.auto()
    ASSESS = enum.auto()
    SCHEDULED = enum.auto()
    IMPLEMENT = enum.auto()
    CLOSED = enum.auto()
    CANCELLED = enum.auto()


class ActivationState(enum.IntEnum):
    NOT_STARTED = enum.auto()
    CHECK_MODULE = enum.auto()
    PRE_CHECK = enum.auto()
    START_ACTIVATION = enum.auto()
    ACTIVATION_COMPLETED = enum.auto()


@dataclasses.dataclass
class Device:
    hostname: str
    ci_item_name: str


class ActivationWorker:
    def __init__(self, esp_instance: str, cr_number: str) -> None:
        self.esp_instance = esp_instance
        self.cr_number = cr_number
        self.change_state = ChangeState.SCHEDULED
        self.activation_state = ActivationState.NOT_STARTED

        # TEST
        self.device = None

    def get_device_info(self) -> Self:
        if _ERROR_ON_GET_DEVICE:
            raise GetDeviceError
        _LOGGER.info("got device info.")
        self.device = Device(hostname="switch-1.cisco.com", ci_item_name="switch-1")
        return self

    def check_module(self) -> Self:
        """Returns True if the action should continue."""
        if _ERROR_ON_CHECK_MODULE:
            raise CheckModuleError

        _LOGGER.info("ran check module.")
        self.activation_state = ActivationState.CHECK_MODULE

        return self

    def implement_change(self) -> Self:
        """Returns True if implemented the change successfully."""
        if _ERROR_ON_IMPLEMENT_CHANGE:
            raise ImplementChangeError

        _LOGGER.info("implemented change request.")
        self.change_state = ChangeState.IMPLEMENT
        return self

    def activation_pre_checks(self) -> Self:
        """Returns True if prechecks are successful."""
        if _ERROR_ON_PRE_CHECKS:
            raise PreCheckError

        _LOGGER.info("ran pre checks on device: %s.", self.device)
        self.activation_state = ActivationState.PRE_CHECK
        return self

    def activate_device(self) -> Self:
        """Returns True if activation was successful."""
        self.activation_state = ActivationState.START_ACTIVATION
        if _ERROR_ON_ACTIVATION:
            raise ActivationError

        _LOGGER.info("activated device: %s.", self.device)
        self.activation_state = ActivationState.ACTIVATION_COMPLETED
        return self

    def close_change(self) -> Self:
        if _ERROR_ON_CLOSE_CHANGE:
            raise CloseChangeError

        if self.activation_state != ActivationState.ACTIVATION_COMPLETED:
            _LOGGER.info("change closed unsuccessfully")
            return
        self.change_state = ChangeState.CLOSED
        _LOGGER.info("change closed successfully")
        return self

    def cancel_change(self) -> Self:
        if _ERROR_ON_CANCEL_CHANGE:
            raise CancelChangeError

        self.change_state = ChangeState.CANCELLED
        _LOGGER.info("change closed successfully")
        return self

    def upload_artifacts(self) -> Self:
        if _ERROR_ON_UPLOAD_ARTIFACTS:
            raise UploadArtifactsError

        _LOGGER.info("uploaded artifacts")
        return self

    def create_service_offering_incident(self, error: Exception) -> Self:
        if _ERROR_ON_CREATE_INCIDENT:
            raise CreateIncidentError
        _LOGGER.info("created incident for error: %r.", error)
        return self

    def create_software_incident(self, error: Exception) -> Self:
        _LOGGER.info("created software incident for error: %r.", error)
        return self

    def create_incident(self, error: Exception) -> Self:
        if isinstance(error, ActivationError):
            return self.create_service_offering_incident(error=error)
        return self.create_software_incident(error=error)

    def handle_error(self, error: Exception) -> Self:
        if _ERROR_ON_CREATE_INCIDENT:
            raise CreateIncidentError

        if isinstance(error, GetDeviceError):
            _LOGGER.info("handling get device error")
            if self.change_state == ChangeState.IMPLEMENT:
                self.close_change().upload_artifacts().create_incident(error)
            else:
                self.cancel_change().upload_artifacts().create_incident(error)

        if isinstance(error, CheckModuleError):
            _LOGGER.info("handling check module error")
            if self.change_state == ChangeState.IMPLEMENT:
                self.close_change().upload_artifacts().create_incident(error)
            else:
                self.cancel_change().upload_artifacts().create_incident(error)

        if isinstance(error, PreCheckError):
            _LOGGER.info("handling pre check error")
            self.close_change().upload_artifacts().create_incident(error)

        if isinstance(error, ActivationError):
            _LOGGER.info("handling activation error")
            self.close_change().upload_artifacts().create_incident(error)

        if isinstance(error, CloseChangeError):
            _LOGGER.info("handling close change error")
            time.sleep(3)
            try:
                self.close_change().upload_artifacts()
            except (CloseChangeError, UploadArtifactsError):
                self.create_incident(error=error)

        if isinstance(error, UploadArtifactsError):
            _LOGGER.info("handling upload artifact error")
            time.sleep(3)
            self.upload_artifacts()

        return self

    def run_activation(self, steps: Iterable[Callable[..., Self]]) -> None:
        try:
            for step in steps:
                step()
        except (
            GetDeviceError,
            CheckModuleError,
            ImplementChangeError,
            PreCheckError,
            ActivationError,
            CloseChangeError,
            CancelChangeError,
            UploadArtifactsError,
        ) as error:
            self.handle_error(error)


def main():
    logging.basicConfig(level=logging.INFO, handlers=(logging.StreamHandler(),))
    worker = ActivationWorker("cisco", "CHG1234")
    worker.run_activation(
        steps=[
            worker.get_device_info,
            worker.check_module,
            worker.implement_change,
            worker.activation_pre_checks,
            worker.activate_device,
            worker.close_change,
            worker.upload_artifacts,
        ]
    )


if __name__ == "__main__":
    main()
