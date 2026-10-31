"""Default implementation of DispatchPolicyProvider."""

from engine.contracts.policy import DispatchPolicy, DispatchPolicyProvider


class DefaultPolicyProvider(DispatchPolicyProvider):
    """
    Default in-memory dispatch policy provider with approved operational defaults.
    """

    def __init__(self, initial_policy: DispatchPolicy | None = None) -> None:
        if initial_policy is not None:
            initial_policy.validate()
            self._policy = initial_policy
        else:
            self._policy = DispatchPolicy()
            self._policy.validate()

    def get_policy(self, zone_id: str | None = None) -> DispatchPolicy:
        """Returns the active DispatchPolicy."""
        return self._policy

    def update_policy(self, new_policy: DispatchPolicy, zone_id: str | None = None) -> None:
        """Validates and updates the active policy dynamically."""
        new_policy.validate()
        self._policy = new_policy
