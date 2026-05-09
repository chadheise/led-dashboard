from abc import ABC, abstractmethod


class Canvas(ABC):
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    @abstractmethod
    def set_pixel(self, x: int, y: int, r: int, g: int, b: int) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    async def render(self) -> None: ...
