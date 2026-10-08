"""A UI-independent surface gesture using the existing placement commands."""
from .placement import raycast_surface


class SurfaceDrag:
    """One surface gesture is one transaction, regardless of update count.

    A miss preserves the last valid pose. The moving instance is excluded from
    surface tests; locked support geometry remains eligible. The caller supplies
    its camera and viewport rather than any Editor/UI object.
    """

    def __init__(self, commands, entity_or_id):
        entity = (commands.scene.find_by_id(entity_or_id)
                  if isinstance(entity_or_id, str) else entity_or_id)
        if entity is None or entity not in commands.scene.root_entities:
            raise ValueError("Surface Drag requires a scene instance")
        if entity.locked:
            raise ValueError("Entity is locked: " + entity.entity_id)
        self.commands = commands
        self.entity = entity
        self.entity_id = entity.entity_id
        commands.begin_transaction("Surface Drag")
        # Ownership prevents a stale gesture from closing a later transaction.
        self._transaction = commands._transaction

    @property
    def active(self):
        return (self._transaction is not None and
                self.commands._transaction is self._transaction)

    def update(self, camera, screen_pos, rect):
        if not self.active:
            return False
        entity = self.commands.scene.find_by_id(self.entity_id)
        if entity is not self.entity or entity.locked:
            self.finish()
            return False
        hit = raycast_surface(self.commands.scene, camera, screen_pos, rect,
                              exclude=entity, fallback=None)
        if hit is None:
            return False
        self.commands.place_on_surface(entity, hit)
        return True

    def finish(self, cancel=False):
        if self.active:
            entity = self.commands.scene.find_by_id(self.entity_id)
            # If external code locked/deleted the instance during this gesture,
            # keep that operation instead of restoring a stale scene snapshot.
            if cancel and entity is self.entity and not entity.locked:
                self.commands.cancel_transaction()
            else:
                self.commands.commit_transaction()
        self._transaction = None
