import functools
from typing import Any, Callable, TypeVar

T = TypeVar('T')


def patch(target_object: Any, attribute_name: str,
          patch_value: Any) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    A decorator factory that patches an attribute of an object for the duration
    of a function's execution.

    Args:
        target_object (Any): The object (e.g., class instance, module) to patch.
        attribute_name (str): The name of the attribute or method to replace.
        patch_value (Any): The new value or function to use as the patch.

    Returns:
        A decorator that can be applied to a function.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        """This is the actual decorator. It takes a function and returns a wrapped version of it."""

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            """
            This is the wrapper function. It executes extra logic before and after
            calling the original function.
            """
            # Check if the target attribute exists
            if not hasattr(target_object, attribute_name):
                raise AttributeError(
                    f'{target_object} does not have attribute {attribute_name}'
                )

            # 1. Save the original value (similar to __enter__)
            original_value = getattr(target_object, attribute_name)

            # Use a try...finally block to ensure the patch is always reverted
            try:
                # 2. Apply the patch (similar to __enter__)
                setattr(target_object, attribute_name, patch_value)

                # 3. Execute the original decorated function
                result = func(*args, **kwargs)
                return result
            finally:
                # 4. Restore the original value (similar to __exit__)
                setattr(target_object, attribute_name, original_value)

        return wrapper

    return decorator
