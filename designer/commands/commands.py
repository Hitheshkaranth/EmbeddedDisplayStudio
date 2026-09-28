from PySide6.QtGui import QUndoCommand


class CallbackCommand(QUndoCommand):
    """Small command primitive; domain values remain in the designer model."""
    def __init__(self, text, redo, undo):
        super().__init__(text)
        self._redo_callback = redo
        self._undo_callback = undo

    def redo(self):
        self._redo_callback()

    def undo(self):
        self._undo_callback()


class NudgeCommand(QUndoCommand):
    """Arrow-key moves of a selection. Consecutive nudges of the same widgets
    merge into one step, so holding an arrow key is one undo, not forty."""
    ID = 0x4E44

    def __init__(self, workspace, models, dx, dy):
        super().__init__("Nudge")
        self._workspace = workspace
        self._models = list(models)
        self._dx, self._dy = dx, dy

    def id(self):
        return self.ID

    def mergeWith(self, other):
        if [id(m) for m in other._models] != [id(m) for m in self._models]:
            return False
        self._dx += other._dx
        self._dy += other._dy
        return True

    def _move(self, sign):
        for model in self._models:
            model.geometry["x"] += sign * self._dx
            model.geometry["y"] += sign * self._dy
        self._workspace._load_page(select=[m.id for m in self._models])

    def redo(self):
        self._move(1)

    def undo(self):
        self._move(-1)
