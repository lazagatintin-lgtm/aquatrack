class BaseEntity:
    """Shared base for domain entities.

    Each model may keep a database record id and its generated code.
    """

    def __init__(self, entity_id=None, code=None):
        self.entity_id = entity_id
        self.code = code

    @property
    def id(self):
        return self.entity_id

    def __repr__(self):
        return f"{self.__class__.__name__}(id={self.entity_id!r}, code={self.code!r})"
