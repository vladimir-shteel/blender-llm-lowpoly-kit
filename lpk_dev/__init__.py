"""Development-only tools of the kit, never shipped: a release builds the production kit
without lpk_dev, tests/ and dev/, and nothing in lpk imports lpk_dev.

fingerprint snapshots every array a stage leaves on a built model and compares two snapshots, for the
same-version determinism check (CONTRIBUTING.md, 'Verifying a change').

Inside Blender, bootstrap as for lpk, purging lpk_dev too:

    for name in [n for n in sys.modules if n == 'lpk' or n.startswith(('lpk.', 'lpk_'))]:
        del sys.modules[name]
    from lpk_dev import fingerprint
    fingerprint.snapshot({'model': '<Name>'}, r'<out>.npz')
"""
