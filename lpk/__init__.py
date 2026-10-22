"""lowpoly-kit: low-poly character modelling in Blender for AI agents (see README.md, ARCHITECTURE.md).

Bootstrap from an MCP execute_blender_code call:

    import sys
    KIT = r'<path to the lowpoly-kit folder>'
    if KIT not in sys.path:
        sys.path.insert(0, KIT)
    for name in [n for n in sys.modules if n == 'lpk' or n.startswith(('lpk.', 'lpk_'))]:
        del sys.modules[name]          # Blender keeps modules between calls: read the kit and lpk_local again
    from lpk import run
    report = run.model(r'<model folder>/<model>.py', stages=('build',))

lpk.run lists the stages and what each reads from the model module.
"""
__version__ = '0.3.0'
