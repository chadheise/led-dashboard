from abc import ABC, abstractmethod


class Canvas(ABC):
    def __init__(self, width: int, height: int, brightness: int = 100) -> None:
        self.width = width
        self.height = height
        self.brightness = brightness

    @abstractmethod
    def set_pixel(self, x: int, y: int, r: int, g: int, b: int) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    async def render(self) -> None: ...

    def set_brightness(self, brightness: int) -> None:
        """Update display brightness (0-100). Subclasses extend this to apply
        the change to the underlying display."""
        self.brightness = brightness
