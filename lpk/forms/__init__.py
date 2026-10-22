"""The shared shape library: body-part forms built from Builder and lpk.core.shapes, one module per body
area. A model supplies measurements, palette names and placement and composes these forms. A form a model
needs that is missing here is written in the local library, in the package of the model that first uses
it, lpk_local.forms.<model> (at the kit's root, ignored by git); it moves here only when the human asks
(ARCHITECTURE.md "Extending the kit"). No module of lpk imports lpk_local."""
