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
